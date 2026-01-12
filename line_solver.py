import logging
from rapidfuzz import fuzz
from synonyms import normalize
from llm import match_script_segment

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def load_cached_llm_segment():
  import json
  import os
  if not os.path.exists("llm_segments.json"):
    return {}
  try:
    with open("llm_segments.json", "r") as f:
      obj = json.load(f)
      if isinstance(obj, dict):
        return {int(k):v for k,v in obj.items()}
      else:
        return {}
  except Exception as e:
    logger.error(f"Failed to load cache: {e}")
    return {}

def store_cached_llm_segment(llm_cache):
  import json
  with open("llm_segments.json", "w") as f:
    json.dump(llm_cache, f, indent=2, ensure_ascii=False)

def single_match(script_a:list[str], script_b:list[str], matches:list[dict], anchors:dict[int,int]):

  llm_cache = load_cached_llm_segment()
  
  for match in matches:
    pos_a = match['pos_a']
    if pos_a in anchors.keys() and pos_a + 1 in anchors.keys() and pos_a + 2 in anchors.keys():
      continue
      logger.info(f"窗口匹配：{pos_a}->{anchors[pos_a]}")
      logger.info(f"  内容: {match['text_a']}")
      if not any(m['pos_b'] == anchors[pos_a] for m in match['matches']):
        logger.info("  匹配位于Top-3之外")
      for i, m in enumerate(match['matches']):
          logger.info(f"  Top-{i+1} 匹配 (B第 {m['pos_b']} 行, 分数 {m['score']}%):")
          logger.info(f"    {m['text_b']}")

    elif pos_a in anchors.keys():
      continue
      logger.info(f"仅本行匹配：{pos_a}->{anchors[pos_a]}")
      logger.info(f"  {pos_a}内容: {match['text_a']}")
      if not any(m['pos_b'] == anchors[pos_a] for m in match['matches']):
        logger.info(f"  {pos_a}匹配位于Top-3之外")
      for i, m in enumerate(match['matches']):
          logger.info(f"  Top-{i+1} 匹配 (B第 {m['pos_b']} 行, 分数 {m['score']}%):")
          logger.info(f"    {m['text_b']}")
      # 检查 pos_a + 1
      if pos_a + 1 < len(script_a):
        next_match = next((m for m in matches if m['pos_a'] == pos_a + 1), None)
        if next_match:
          if pos_a + 1 in anchors.keys():
            logger.info(f"  {pos_a + 1}已匹配->{anchors[pos_a + 1]}")
            if not any(m['pos_b'] == anchors[pos_a + 1] for m in next_match['matches']):
              logger.info(f"  {pos_a + 1}匹配位于Top-3之外")
          else:
            logger.info(f"  {pos_a + 1}无匹配")           
          logger.info(f"  {pos_a + 1}内容: {next_match['text_a']}") 
          for i, m in enumerate(next_match['matches']):
            logger.info(f"  Top-{i+1} 匹配 (B第 {m['pos_b']} 行, 分数 {m['score']}%):")
            logger.info(f"    {m['text_b']}")

      # 检查 pos_a + 2
      if pos_a + 2 < len(script_a):
        next_match2 = next((m for m in matches if m['pos_a'] == pos_a + 2), None)
        if next_match2:
          if pos_a + 2 in anchors.keys():
            logger.info(f"  {pos_a + 2}已匹配->{anchors[pos_a + 2]}")
            if not any(m['pos_b'] == anchors[pos_a + 2] for m in next_match2['matches']):
              logger.info(f"  {pos_a + 2}匹配位于Top-3之外")
          else:
            logger.info(f"  {pos_a + 2}无匹配")
          logger.info(f"  {pos_a + 2}内容: {next_match2['text_a']}")
          for i, m in enumerate(next_match2['matches']):
            logger.info(f"  Top-{i+1} 匹配 (B第 {m['pos_b']} 行, 分数 {m['score']}%):")
            logger.info(f"    {m['text_b']}")

  def get_norm_text_b(pos_b, window_size=3):
    return " / ".join(map(normalize, script_b[pos_b-(window_size//2):pos_b+(window_size//2)+1]))

  def get_text_b(pos_b, window_size=3):
    return " / ".join(script_b[pos_b-(window_size//2):pos_b+(window_size//2)+1])

  def get_text_a(pos_a, window_size=3):
    return " / ".join(script_a[pos_a-(window_size//2):pos_a+(window_size//2)+1])

  def get_norm_text_a(pos_a, window_size=3):
    return " / ".join(map(normalize, script_a[pos_a-(window_size//2):pos_a+(window_size//2)+1]))
    
      
  single_matches = { k:v for k,v in anchors.items()}
  multiple_matches = {}
  pos_a_to_match = {m['pos_a']: m for m in matches}
  for pos_a in pos_a_to_match:
    if all(pos_a + i in single_matches for i in range(3)):
      continue
    candidates = set()
    curr_match = pos_a_to_match[pos_a]
    next_match1 = pos_a_to_match.get(pos_a + 1)
    next_match2 = pos_a_to_match.get(pos_a + 2)
    for match in [curr_match, next_match1, next_match2]:
      if match:
        for m in match['matches']:
          candidates.add(m['pos_b'])
          candidates.add(m['pos_b'] + 1)
          candidates.add(m['pos_b'] + 2)
    for p in [pos_a, pos_a + 1, pos_a + 2]:
      if p in single_matches:
        p_b = single_matches[p]
        candidates.add(p_b)
        candidates.add(p_b + 1)
        candidates.add(p_b + 2)

    for p in [pos_a, pos_a + 1, pos_a + 2]:
      if p in single_matches:
        continue
      else:
        score_map = {c : fuzz.WRatio(normalize(script_a[p]), normalize(script_b[c])) for c in candidates}
        candidates = { c : score_map[c] for c in candidates if score_map[c] >= 92}
        max_score = 0.0
        max_c = None
        max_norm_text = ""
        for c in sorted(candidates):
          score = score_map[c]
          if score > max_score:
            max_score = score
            max_c = c
            max_norm_text = get_norm_text_b(c)
        if max_c is not None:
          
          if len(candidates) == 1 or len([c for c in candidates if score_map[c] == max_score]) == 1:
            # logger.info(f"  候选位置 {max_c} 相似度 {max_score} (选中): {script_b[max_c]} -> {normalize(script_b[max_c])}")
            single_matches[p] = max_c
          elif all(max_norm_text == get_norm_text_b(c) for c in candidates):
            # logger.info(f"  候选位置 {max_c} 相似度 {max_score} (选中): {script_b[max_c]} -> {normalize(script_b[max_c])}")
            single_matches[p] = max_c
          else:
            logger.info(f"在3-gram({pos_a}, {pos_a + 1}, {pos_a + 2})中：")
            logger.info(f"匹配{p}的内容: {get_text_a(p,5)} -> {normalize(get_text_a(p,5))}")
            logger.info(f"匹配{p}的候选位置: {sorted(candidates)}")
            for c in sorted(candidates):
              norm_text_c = get_norm_text_b(c,5)
              text_c = get_text_b(c,5)
              logger.info(f"  候选位置 {c} 相似度 {score_map[c]} : {text_c} -> {norm_text_c}")
            if p not in llm_cache:
              llm_match = match_script_segment(get_text_a(p,5), [{"id": c, "lines": [get_text_b(c,5)]} for c in sorted(candidates)])
              llm_cache[p] = llm_match
            else :
              llm_match: dict = llm_cache[p]
            logger.info(f"LLM匹配结果：{llm_match}")
            if llm_match['selected_id'] is not None:
              single_matches[p] = llm_match['selected_id']
            else :
              multiple_matches[p] = list(candidates)

  store_cached_llm_segment(llm_cache)

  final_matches = {k:[v] for k,v in single_matches.items()}
  final_matches.update(multiple_matches)

  return final_matches
