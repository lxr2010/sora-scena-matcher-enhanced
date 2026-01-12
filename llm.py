import json
from dotenv import load_dotenv
from openai import OpenAI
import os
import logging 

logger = logging.getLogger()

# 默认配置（可根据你的服务商修改）
load_dotenv()
client = OpenAI(
    base_url=os.getenv("OPENAI_BASE_URL"),
    api_key=os.getenv("OPENAI_API_KEY")
)

def call_llm_for_local_alignment(sub_a, sub_b):
    """
    sub_a: 剧本A的子列表 (list of strings)
    sub_b: 剧本B的子列表 (list of strings)
    """
    
    # 构建输入文本，带上索引以便LLM引用
    formatted_a = "\n".join([f"A[{i}]: {text}" for i, text in enumerate(sub_a)])
    formatted_b = "\n".join([f"B[{j}]: {text}" for j, text in enumerate(sub_b)])

    system_prompt = """你是一个高精度的剧本语音对齐专家。
任务：判断剧本 A 的每一行与剧本 B 的对应行是否可以共用【同一段语音文件】。
### 核心逻辑：
判定标准不是“字面相等”，而是“听感兼容”。
只要玩家在看 B 文本时，听 A 的语音不会感到明显的词汇错误或剧情偏差，即视为匹配。
### 判定准则（语感兼容）：
1. **1.0 (完美)**：文字一致，或仅有标点、空格、全半角差异（如：十中八九 vs 十中八、九）。
2. **0.9 (口语/缩略语)**：包含口语缩略变化（如：言っとく vs 言っておく），语音完全通用。
3. **0.8 (语法/语气微调)**：
   - 敬语层级变化（如：させてもらう vs させていただく）。
   - 结尾语气词变化（如：...た！？ vs ...たか❤）。
   - 微小的状态修饰变化（如：ゴツい vs ゴツそうな），只要核心名词和动作一致。
   - 仅存在标点特殊符号的差异，但在 B 中进行了断句拆分或合并。
4. **0.0 (不可兼容)**：
   - 核心名词/动词被替换（如：把“学校”改成了“屋敷”）。
   - 意思发生根本扭转。
   - 内容在另一方缺失。
### Few-Shot 示例（必须严格参考此格式）：
**输入：**
剧本 A:
A[0]: 行くわよ、みんな！
A[1]: 行くわよ。準備はいいかしら？
A[2]: わかりました。☆
A[3]: すぐに向かいます。
A[4]: 準備は整いました。
A[5]: 時間がありませんから。
A[6]: これもあの語呂合わせのおかげかな。
A[7]: お腹が空きましたね。
剧本 B:
B[0]: 行くわよ、みんな……☆
B[1]: 行くわよ。
B[2]: 準備はいいかしら？
B[3]: わかりました、すぐに向かいます。
B[4]: 準備は整ったわ。
B[5]: ……助かりました。
B[6]: 結構デタラメだったんだけど。
B[7]: 腹減ったな。
**输出：**
{
  "alignment": [
    { "a": [0], "b": [0], "score": 1.0, "reason": "仅标点符号和特殊符号差异。" },
    { "a": [1], "b": [1, 2], "score": 0.9, "reason": "文本一致，A[1]在B中被拆分为两句（拆分）。" },
    { "a": [2, 3], "b": [3], "score": 0.9, "reason": "文本一致，A的连续两句在B中被合并为一句（合并）。" },
    { "a": [4], "b": [4], "score": 0.8, "reason": "核心词'準備/整う'一致，仅敬语语气微调。" },
    { "a": [5], "b": null, "score": 0.0, "reason": "A[5]的内容在剧本B中被删除。" },
    { "a": null, "b": [5], "score": 0.0, "reason": "B[5]是新增台词，A中无对应语音。" },
    { "a": [6], "b": null, "score": 0.0, "reason": "核心词替换（语吕合わせ vs デタラメ），语音不兼容。" },
    { "a": [7], "b": null, "score": 0.0, "reason": "核心句式完全重写（お腹空いた vs 腹減った），不可重用语音。" }
  ]
}
** 输入：**
剧本 A:
A[0]: 何をしている！
A[1]: 早く行け！！
剧本 B:
B[0]: 何をしている！早く行け！！
** 输出：**
{
  "alignment": [
    { "a": [0,1], "b": [0], "score": 0.9, "reason": "文本一致，A[0]和A[1]在B中合并为一句（合并）。"}
  ]
}
### 任务要求：
1. 必须分析剧本 A 的每一行。
2. 结果必须严格按照 JSON 格式输出，所有对齐项放在 "alignment" 数组中。
3. 只要分数低于 0.8，b 必须设为 null。
"""
    user_prompt = f"""
### 待处理剧本：
剧本 A:
{formatted_a}
剧本 B:
{formatted_b}
请输出对齐结果 JSON："""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", # 或 deepseek-chat, qwen-turbo 等小模型
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}, # 强制要求返回 JSON
            temperature=0.1 # 降低随机性，保证稳定性
        )
        
        # 解析返回内容
        result = json.loads(response.choices[0].message.content)
        logger.info(f"LLM Alignment Result: {result}")
        return result.get("alignment", [])

    except Exception as e:
        logger.error(f"LLM Alignment Error: {e}")
        return None

def match_script_segment(source_segment, candidates):
    """
    source_segment: list of 5 strings [prev_prev, prev, target, next, next_next]
    candidates: list of dicts [{'id': 123, 'lines': [5 lines]}, ...]
    """
    
    system_prompt = """
# Role
你是一个严格的文本对齐工具，专门用于日语游戏剧本匹配。

# Task
在“候选列表”中找到与“源片段”最匹配的项。

# Evaluation Criteria
1. 文本匹配度：优先考虑中间的目标句（第3句）。
2. 上下文指纹：对比前后各2句的文本重合度。
3. 容错性：允许轻微的标点符号差异或语气助词（如 'だ' vs 'です'）的变化。
4. 唯一性要求：
   - 如果某个候选者的 5 句序列与源片段高度吻合且明显优于其他项，则选中该 ID。
   - 如果存在多个候选者匹配程度完全一致（即无法唯一确定），必须返回 null。
   - 如果没有任何候选者与目标句（第3句）语义一致，必须返回 null。

# Constraints
- 不要依赖任何关于剧情、角色身份或游戏逻辑的外部知识。
- 只根据提供的文本内容进行字面和语义对比。

# Output Format (JSON only)
{
  "selected_id": number or null,
  "confidence": number (0-100),
  "reason": "简短的匹配依据说明"
}
"""

    # 格式化输入数据
    user_content = {
        "source": {
            "context_before": source_segment[:2],
            "target": source_segment[2],
            "context_after": source_segment[3:]
        },
        "candidates": [
            {"id": c['id'], "lines": c['lines']} for c in candidates
        ]
    }

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_content, ensure_ascii=False)}
            ],
            response_format={"type": "json_object"},
            temperature=0  # 设置为0以获得最确定的结果
        )
        
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        logger.error(f"Error during API call: {e}")
        return {"selected_id": None, "confidence": 0, "reason": "Error"}

def call_llm_to_identify_redundant(jp_block, tr_block):
    """
    使用 OpenAI GPT-4o-mini 精确识别多余行索引
    """
    # 将对象列表转换为纯文本格式供 LLM 阅读
    jp_content = "\n".join([f"{i}: {line.text}" for i, line in enumerate(jp_block)])
    tr_content = "\n".join([f"{i}: {line.text}" for i, line in enumerate(tr_block)])
    prompt = f"""
你是一个精通日语和中文的剧本对齐助手。
对比以下两段剧本。日语原文是标准，中文翻译中由于错误多出了几行（可能是译者注、重复台词或无关文本）。
请找出中文翻译中多余行的索引。
日语原文：
{jp_content}
中文翻译：
{tr_content}
任务：
1. 逐行对比语义。
2. 找出中文翻译中多出的、在日语中没有对应内容的索引。
3. 最后一行为同步锚点，通常是匹配的，不要删除。
4. 返回格式必须为 JSON: {{"redundant_indices": [数字列表]}}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # 建议用 mini，处理这类任务性价比最高
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs only JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        return result.get("redundant_indices", [])
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        return []

def call_llm_to_verify_alignment(jp_line, tr_line):
    """
    判断单行（或给定两行）是否语义匹配
    """
    prompt = f"""
Role: 你是一位精通日语和中文的 JRPG（日式角色扮演游戏）资深汉化审核员，特别熟悉《英雄传说：空之轨迹》的语言风格。
Task: 请判断给出的日文原句与中文译句在游戏语境下表达的意思是否一致。
Strict Rules (必须严格执行):
1. 身份识别： 在《空之轨迹》等日系游戏中，年幼女性或特定性格角色常用自己的名字（如“库鲁塞”、“艾丝蒂尔”）自称。也存在使用名字指代“你”的情况。在对比时，必须允许此类转换。
意译许可： 游戏汉化允许为了符合中文习惯进行的微调。例如：将“雇佣”译为“委托”，将“努力”译为“加油”，只要角色动机、情感倾向和传达的事实一致，即判定为“意思相同”。
忽略语法差异： 不要纠结于主动/被动语态或时态的细微字面差别，重点看“谁对谁做了什么”以及“说话人的意图”。
判断标准： 如果这两句话在同一个游戏场景中能让玩家获得相同的信息和感受，请回答“语义一致”。

待处理文本：
日文：{jp_line.text}
中文：{tr_line.text}
请仅返回 JSON：{{"match": true}} 或 {{"match": false}}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "Only output JSON."},
                      {"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        logger.info(f"JP: {jp_line.text} ;SC: {tr_line.text} ")
        logger.info(f"LLM Alignment Result: {response.choices[0].message.content}")
        return json.loads(response.choices[0].message.content).get("match", False)
    except Exception as e:
        logger.error(f"LLM Alignment Error: {e}")
        return False

# --- 使用示例 ---
def test_match_segment():
    source_5_lines = [
        "はーい。",
        "お世話になります。",
        "ありがとう。今回は本当に助かったよ。",
        "それと、悪かったね。中途半端な结果にしてしまって。",
        "気にしないでください。色々と勉强させてもらいました。"
    ]

    candidate_list = [
        {
            "id": 3758,
            "lines": [
                "とにかく事情を聞いてみよう。",
                "ティオ、どこにいるのかな？",
                "ありがとう。今回は本当に助かったよ。",
                "それと、悪かったね。中途半端な結果にしてしまって。",
                "気にしないでください。色々と勉強させてもらいました。"
            ]
        },
        {
            "id": 3941,
            "lines": [
                "嬉しい事を言ってくれるじゃないか。",
                "それじゃ、期待に沿えるようはりきって作るとしようかねぇ。",
                "ありがとう。今回は本当に助かったよ。",
                "それと、悪かったね。中途半端な結果にしてしまって。",
                "気にしないでください。色々と勉強させてもらいました。"
            ]
        }
    ]

    match_result = match_script_segment(source_5_lines, candidate_list)
    print(json.dumps(match_result, indent=2, ensure_ascii=False))


# --- 使用示例 ---
def test_local_alignment():
    sub_a = [
        "やったねヨシュア!これで晴れてあたしたちも協会の一员よ",
        "そうか、僕が遊撃士か......"
    ]
    sub_b = [
        "やったねヨシュア!これで晴れてあたしたちも協会の一员よ☆そうか、僕が遊撃士か......"
    ]
#  A[19517]: メーヴェ海道沿いの砂浜にガケに囲まれた窪地のような場所があってね。
#  A[19518]: その場所こそ──ズバリこの△印で描かれている地点だと思うんだ。
#  B[12693]: メーヴェ海道沿いの砂浜にガケに囲まれた窪地のような場所があるんだけど……
#  B[12694]: 宝の地図にはその窪地が目印として描かれているんだ。
    sub_a += [
        "メーヴェ海道沿いの砂浜にガケに囲まれた窪地のような場所があってね。",
        "その場所こそ──ズバリこの△印で描かれている地点だと思うんだ。"
    ]
    sub_b += [
        "メーヴェ海道沿いの砂浜にガケに囲まれた窪地のような場所があるんだけど……",
        "宝の地図にはその窪地が目印として描かれているんだ。"
    ]
#  A[0]: これもあの語呂合わせのおかげかな。
#  A[1]: “御用よ、ハイヤー！”、だっけ。
#  A[2]: ワードのチョイスはともあれ、確かに覚えやすかったかもね。
#  B[0]: 結構デタラメだったんだけど、たまたま合ってたみたい。
#  B[1]: やっぱり。
#  B[2]: まったく、君って子は……
    sub_a += [
        "これもあの語呂合わせのおかげかな。",
        "御用よ、ハイヤー！、だっけ。",
        "ワードのチョイスはともあれ、確かに覚えやすかったかもね。"
    ]
    sub_b += [
        "結構デタラメだったんだけど、たまたま合ってたみたい。",
        "やっぱり。",
        "まったく、君って子は……"
    ]
#  A[0]: あとは、オーブメントを交換して…………と。
#  B[0]: あとは、オーブメントを
#  B[1]: 交換して…………と。
    sub_a += [
        "あとは、オーブメントを交換して…………と。"
    ]
    sub_b += [
        "あとは、オーブメントを☆",
        "交換して…………と。"
    ]
    alignment = call_llm_for_local_alignment(sub_a, sub_b)
    print(alignment)
    # 输出预想: [{"a": [0, 1], "b": [0]}]

if __name__ == "__main__":
    test_match_segment()
