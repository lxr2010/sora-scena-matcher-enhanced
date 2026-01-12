from pydantic import TypeAdapter, BaseModel
from models import RemakeLine, Line
from script_matcher import ScriptMatcher
from script_chainer import SceneChainer
import json

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(message)s')
fh = logging.FileHandler('match.log', mode='w', encoding='utf-8')
fh.setLevel(logging.INFO)
fh.setFormatter(formatter)
logger.addHandler(fh)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter)
logger.addHandler(ch)


class Script :
  def __init__(self, file:str) -> None:
    with open(file, "r") as f:
      adapter = TypeAdapter(list[Line])
      self.lines = adapter.validate_json(f.read())

    self.texts = [line.text for line in self.lines]

class RemakeScript :
  NEW_ID_START=50001
  def __init__(self, file:str) -> None:
    self.lines = []
    with open(file, "r") as f:
        commands: list[dict] = json.load(f)
        for i, entry in enumerate(commands):
            remake_line = RemakeLine(id=self.NEW_ID_START + i, **entry)
            self.lines.append(remake_line)
    self.texts = [line.text for line in self.lines]

def main():
  # 剧本 B: 乱序
  script = Script("script_data.json")
  # 剧本 A：原始顺序
  remake_script = RemakeScript("scena_data_jp_Command.json")

  matcher = ScriptMatcher(threshold=0.8)
  matcher.build_index(remake_script.texts)
  matches = matcher.match(script.texts)

  for m in matches:
    m['len'] = 3 

  chainer = SceneChainer(matches, min_chain_score=300)
  scenes = chainer.extract_all_scenes()

  with open("matches.json", "w") as f:
    json.dump(matches, f, indent=2)

  with open("matched_scenes.json", "w") as f:
    json.dump(scenes, f, indent=2)

  logger.info("\n--- 匹配结果 ---")
  for idx, scene in enumerate(scenes):
    logger.info(f"--- 发现场次 {idx+1} (总分: {scene['total_score']}) ---")
    logger.info(f"  在剧本 A 中的位置: {scene['a_range'][0]} - {scene['a_range'][1]} 行")
    logger.info(f"  在剧本 B 中的位置: {scene['b_range'][0]} - {scene['b_range'][1]} 行")
    for m in scene["segments"]:
      logger.info(f"[相似度 {m['score']}%] B行:{m['pos_b']} -> A行:{m['pos_a']}")
      logger.info(f"  A内容: {m['text_a']}")
      logger.info(f"  B内容: {m['text_b']}")
  logger.info("\n--- 匹配统计 ---")
  logger.info(f"剧本A总台词数: {len(remake_script.texts)}")
  logger.info(f"匹配到的台词数: {sum(len(scene['segments']) for scene in scenes)}")

if __name__ == "__main__":
  main()