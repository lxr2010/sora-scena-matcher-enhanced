import json
import logging 
from models import RemakeScript, Script, RemakeLine, Line
from llm import call_llm_to_identify_redundant, call_llm_to_verify_alignment
import csv

logger = logging.getLogger()

def solve_alignment(jp_list, tr_list):
    i = 0
    step = 50  # 步进步长
    
    while i < len(jp_list) and i < len(tr_list):
        # 1. 尝试跳跃步进检查
        check_idx = min(i + step, len(jp_list) - 1, len(tr_list) - 1)
        
        # 如果步进点匹配，直接跳过这一段
        if call_llm_to_verify_alignment(jp_list[check_idx], tr_list[check_idx]):
            print(f"进度: {check_idx}/{len(jp_list)} - 片段对齐正常")
            i = check_idx + 1
            continue
        
        # 2. 发现错位，开始二分查找第一个错位点
        print(f"在 {i} 到 {check_idx} 之间发现错位，正在定位...")
        low = i
        high = check_idx
        first_error_idx = high
        
        while low <= high:
            mid = (low + high) // 2
            if call_llm_to_verify_alignment(jp_list[mid], tr_list[mid]):
                low = mid + 1
            else:
                first_error_idx = mid
                high = mid - 1
        
        # 3. 定位到第一个错误点后，取其后一小段由 LLM 判定具体多出的行
        print(f"确定的第一个错位起始点索引: {first_error_idx}")
        
        # 截取窗口：错误点开始的 5 行日文，对 8 行翻译（假设翻译可能多了）
        window_size = 5
        jp_window = jp_list[first_error_idx : first_error_idx + window_size]
        tr_window = tr_list[first_error_idx : first_error_idx + window_size + 3]
        
        redundant_in_window = call_llm_to_identify_redundant(jp_window, tr_window)
        
        if redundant_in_window:
            # 将相对索引转换为全局索引，并从后往前删除以防索引塌陷
            global_indices = [first_error_idx + r for r in redundant_in_window]
            print(f"LLM 识别到多余行索引: {global_indices}")
            
            for r_idx in sorted(global_indices, reverse=True):
                if r_idx < len(tr_list):
                    del tr_list[r_idx]
            
            # 删除后索引已变，不增加 i，重新检查当前位置
        else:
            # 如果 LLM 没找出来，可能是一对多翻译，强制跳过一步避免死循环
            print("LLM 未发现明显多余行，尝试跳过该行。")
            i = first_error_idx + 1
    return tr_list


def explain_llm_alignments(script_a: RemakeScript, script_b: Script):
  try:
    with open("llm_alignments.json", "r") as f:
      llm_alignments:dict[str:dict] = json.load(f)
    with open("llm_segments.json", "r") as f:
      llm_segments:dict[str:dict] = json.load(f)
      llm_segments = { int(k):v for k,v in llm_segments.items() }
    explanations = {}
    for key, aligns in llm_alignments.items():
      # key: curr_a:next_a-curr_b:next_b
      # alignment: {"a":list, "b":list, score:float, reason: str}
      # 恢复 curr_a, next_a, curr_b, next_b
      key_a , key_b = key.split('-')
      curr_a , next_a = key_a.split(':')
      curr_b , next_b = key_b.split(':')
      curr_a = int(curr_a)
      next_a = int(next_a)
      curr_b = int(curr_b)
      next_b = int(next_b)
      for alignment in aligns:
        # logger.info(f"key: {key}, alignment: {alignment}")
        if alignment.get('b') is None or not alignment['b'] or alignment['score'] == 0.0:
          continue
        explained = {}
        explained['a'] = [ curr_a + 1 + rel_a for rel_a in alignment.get('a') or [] ]
        explained['b'] = [ curr_b + 1 + rel_b for rel_b in alignment.get('b') or [] ]
        explained['score'] = alignment.get('score',0.0)
        explained['reason'] = alignment.get('reason','')
        # replace reason's all substrings "A[{rel_a}]" to "A[{script_a[rel_a + 1 + curr_a].id}]" and "B[{rel_b}]" to "B[{script_b[rel_b + 1 + curr_b].script_id}]"
        for rel_a in alignment.get('a') or []:
          explained['reason'] = explained['reason'].replace(f"A[{rel_a}]", f"A[{script_a[rel_a + 1 + curr_a].id}]")
        for rel_b in alignment.get('b') or []:
          explained['reason'] = explained['reason'].replace(f"B[{rel_b}]", f"B[{script_b[rel_b + 1 + curr_b].script_id}]")
        for pos_a in explained['a']:
          explanations[pos_a] = {"b": explained['b'], "reason": explained['reason'], "score": explained['score']}

    for key, match_segment in llm_segments.items():
      # key: pos_a
      # match_segment: {"selected_id": int, "confidence":int, "reason": str}
      explanations[key] = {"b": [match_segment['selected_id']], "reason": match_segment['reason'], "score": match_segment['confidence']/100.0}

      with open("llm_explanations.json", "w") as f:
        json.dump(explanations, f, indent=2, ensure_ascii=False)
      return explanations

  except FileNotFoundError:
    logger.error("At least one of LLM cache file not found.")

def gen_csv(script_a: RemakeScript, script_b: Script, trans_a: RemakeScript, final_matches:dict[int,list], llm_explanations:dict, match_result_csv:str):
  # gpt-4o-mini等大模型做不到精准匹配中日翻译，所以无法实现自动匹配中日翻译条目。
  # trans_a_aligned = solve_alignment(script_a, trans_a)
  trans_map = { t.id : t for t in trans_a}
  with open(match_result_csv, 'w', encoding='utf-8', newline='\n') as f:
    writer = csv.writer(f)
    writer.writerow(['RemakeVoiceID', 'RemakeScenaScriptFilename', 'RemakeScenaScriptLineno', 'RemakeScenaScriptAddStructLineno', 'RemakeScenaScriptTranslationLineno', 'RemakeScenaScriptTranslationAddStructLineno', 'OldScriptId', 'OldVoiceFilename', 'MatchType', 'RemakeVoiceCategory','RemakeVoiceTranslation', 'RemakeVoiceText', 'OldVoiceText',"Annotation"])
    rows_to_write = []
    for pos_a, line_a in enumerate(script_a) :
      row_to_w = []
      row_to_w.append(line_a.id)
      row_to_w.append(line_a.filebase)
      row_to_w.append(line_a.lineno)
      row_to_w.append(line_a.lineno_corr)
      trans_lineno = ""
      trans_lineno_corr = ""
      trans_text = ""
      if line_a.id in trans_map:
        trans_lineno = trans_map[line_a.id].lineno
        trans_lineno_corr = trans_map[line_a.id].lineno_corr
        trans_text = trans_map[line_a.id].text
      row_to_w.append(trans_lineno) # Translation Lineno
      row_to_w.append(trans_lineno_corr) # Translation AddStruct Lineno
      if pos_a in final_matches:
        best_pos_b = final_matches[pos_a][0]
        line_b:Line = script_b[best_pos_b]
        row_to_w.append(line_b.script_id)
        row_to_w.append("ch" + line_b.voice_id)
        row_to_w.append("matched") # match type
        row_to_w.append("voice") # voice category
        row_to_w.append(trans_text) # RemakeVoiceTranslation
        row_to_w.append(line_a.text) # RemakeVoiceText
        row_to_w.append(line_b.text) # OldVoiceText
        # Annotation:
        # 1. Other candidates.
        # 2. LLM Explaination.
        # 3. LLM Score.
        anno = ""
        if len(final_matches[pos_a]) > 1:
          anno += "其他候补ScriptId: " + ",".join([str(script_b[i].script_id) for i in final_matches[pos_a][1:]])
        if pos_a in llm_explanations:
          anno += ";LLM解释: " + llm_explanations[pos_a]['reason']
          anno += ";LLM得分: " + str(llm_explanations[pos_a]['score'])
        row_to_w.append(anno)
      else:
        row_to_w.append("") # Script ID
        row_to_w.append("") # Voice ID
        row_to_w.append("unmatched")
        row_to_w.append("voice") # voice category
        row_to_w.append(trans_text) # RemakeVoiceTranslation
        row_to_w.append(line_a.text) # RemakeVoiceText
        row_to_w.append("") # OldVoiceText
        anno = ""
        if pos_a in llm_explanations:
          anno += "LLM解释: " + llm_explanations[pos_a]['reason']
          anno += ";LLM得分: " + str(llm_explanations[pos_a]['score'])
        row_to_w.append(anno)
      rows_to_write.append(row_to_w)
    writer.writerows(rows_to_write)

      
        

if __name__ == "__main__":
  script_a = RemakeScript("scena_data_jp_Command.json")
  script_b = Script("script_data.json")
  exp = explain_llm_alignments(script_a, script_b)
