import re
import unicodedata
from datasketch import MinHash, MinHashLSH
from rapidfuzz import fuzz
import logging

logger = logging.getLogger()

class ScriptMatcher:
    def __init__(self, threshold=0.9, num_perm=128):
        """
        :param threshold: LSH 粗筛的相似度阈值 (0.0~1.0)
        :param num_perm: 哈希排列次数，越高越准但越慢
        """
        self.threshold = threshold
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self.script_a_windows = {} # 存储窗口原始内容以便后续精算
        self.script_a = []

    def _clean(self, text):
        """日语文本清洗：标准化、去括号、去角色名、去空格"""
        text = unicodedata.normalize('NFKC', text)
        # 去除括号内容（动作指导）
        # text = re.sub(r'[（\(].*?[）\)]', '', text)
        # 去除冒号前的角色名（如 "田中：" 或 "田中:"）
        # text = re.sub(r'^.*?[:：]', '', text)
        # 只保留字母和数字
        return "".join(c for c in text if c.isalnum())

    def _get_minhash(self, text):
        """计算 MinHash 签名"""
        m = MinHash(num_perm=self.num_perm)
        # 使用 2-gram 切分
        shingles = [text[i:i+2] for i in range(len(text)-1)]
        if not shingles: # 处理极短文本
            shingles = [text]
        for s in shingles:
            m.update(s.encode('utf8'))
        return m

    def build_index(self, script_a):
        """对剧本 A 建立三行滑动窗口索引"""
        logger.info(f"正在索引剧本 A (共 {len(script_a)} 行)...")
        self.script_a = script_a
        for i in range(len(script_a) - 2):
            # 组合连续三行
            combined_text = "".join([self._clean(line) for line in script_a[i:i+3]])
            if len(combined_text) < 5: continue # 忽略过短的内容
            
            m = self._get_minhash(combined_text)
            window_id = f"A_pos_{i}"
            self.lsh.insert(window_id, m)
            self.script_a_windows[window_id] = combined_text

    def match(self, script_b, top_k=5):
        """拿剧本 B 去索引中检索匹配片段"""
        results = []
        logger.info(f"开始匹配剧本 B (共 {len(script_b)} 行)...")
        
        for j in range(len(script_b) - 2):
            # 同样获取 B 的三行窗口
            raw_b_lines = script_b[j:j+3]
            clean_b = "".join([self._clean(line) for line in raw_b_lines])
            if len(clean_b) < 5: continue

            # 1. LSH 粗筛 (快速找到相似候选集)
            m_query = self._get_minhash(clean_b)
            candidates = self.lsh.query(m_query)

            # 2. 精确比对 (计算编辑距离得分)
            best_match = None
            max_score = 0
            
            for cand_id in candidates:
                clean_a = self.script_a_windows[cand_id]
                # 使用 RapidFuzz 计算 Token Set Ratio (对乱序和增删很鲁棒)
                score = fuzz.token_set_ratio(clean_a, clean_b)
                
                if score > max_score:
                    max_score = score
                    best_match = cand_id

            # 3. 记录高质量匹配 (得分 80 以上)
            if max_score > 80:
                pos_a = int(best_match.split('_')[-1])
                results.append({
                    "score": round(max_score, 2),
                    "pos_a": pos_a,
                    "pos_b": j,
                    "text_a": " / ".join(self.script_a[pos_a:pos_a+3]),
                    "text_b": " / ".join(raw_b_lines)
                })
        
        # 按 B 的顺序排序
        return results

# --- 测试使用 ---
if __name__ == "__main__":
    # 模拟剧本 A
    script_a = [
        "田中：お疲れ様です。",
        "佐藤：ああ、お疲れ。今日の会議はどうだった？",
        "田中：まあまあでしたね。部長が少し怒っていましたが。",
        "佐藤：またか。あの人はいつもそうだ。",
        "（沈黙が流れる）",
        "田中：明日の資料、作っておきました。"
    ]

    # 模拟剧本 B (顺序乱了，且台词有微小差异)
    script_b = [
        "佐藤：またかよ、あの人は。いつもそうなんだから。", # 差异
        "（静かな時間）", # 差异
        "田中：明日の準備、終わりましたよ。", # 差异
        "田中：お疲れ様です！", # 差异
        "佐藤：お疲れ。今日の会議はどうだったかな？", # 差异
        "田中：まあまあでした。部長が怒ってましたけど。" # 差异
    ]

    matcher = ScriptMatcher(threshold=0.4) # 噪音多时可以降低粗筛阈值
    matcher.build_index(script_a)
    matches = matcher.match(script_b)

    logger.info("\n--- 匹配结果 ---")
    for m in matches:
        logger.info(f"[相似度 {m['score']}%] B行:{m['pos_b']} -> A行:{m['pos_a']}")
        logger.info(f"  A内容: {m['text_a']}")
        logger.info(f"  B内容: {m['text_b']}\n")
