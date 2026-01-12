import numpy as np
import logging

logger = logging.getLogger()

class SceneChainer:
    def __init__(self, matches, min_chain_score=200):
        """
        :param matches: 原始匹配列表 [{"pos_a", "pos_b", "score", "len"}, ...]
        :param min_chain_score: 一个链条（场次）的最低总得分，低于此值则停止提取
        """
        self.matches = sorted(matches, key=lambda x: x['pos_a'])
        self.min_chain_score = min_chain_score

    def _get_best_chain(self, current_matches):
        """使用 DP 找到当前匹配池中的最优单链"""
        n = len(current_matches)
        if n == 0: return [], 0
        
        # dp[i] 表示以 i 结尾的最优链条得分
        dp = [m['score'] for m in current_matches]
        parent = [-1] * n
        
        for i in range(n):
            curr = current_matches[i]
            for j in range(i):
                prev = current_matches[j]
                
                # 约束：在 A 和 B 中都必须是严格递增的（场次内有序）
                # 且不允许重叠（前一个匹配的末尾 <= 当前匹配的开头）
                if (prev['pos_a'] + prev['len'] <= curr['pos_a']) and \
                   (prev['pos_b'] + prev['len'] <= curr['pos_b']):
                    
                    if dp[j] + curr['score'] > dp[i]:
                        dp[i] = dp[j] + curr['score']
                        parent[i] = j
        
        best_idx = np.argmax(dp)
        best_score = dp[best_idx]
        
        # 回溯路径
        chain = []
        curr_idx = best_idx
        while curr_idx != -1:
            chain.append(current_matches[curr_idx])
            curr_idx = parent[curr_idx]
        
        return chain[::-1], best_score

    def extract_all_scenes(self):
        """循环提取，直到没有高质量链条为止"""
        all_scenes = []
        remaining_matches = list(self.matches)
        
        while True:
            # 1. 找到当前最好的链
            chain, score = self._get_best_chain(remaining_matches)
            
            # 2. 如果分数太低（说明剩下的都是杂讯），停止
            if score < self.min_chain_score:
                break
            
            all_scenes.append({
                "total_score": score,
                "segments": chain,
                "a_range": (chain[0]['pos_a'], chain[-1]['pos_a'] + chain[-1]['len']),
                "b_range": (chain[0]['pos_b'], chain[-1]['pos_b'] + chain[-1]['len'])
            })
            
            # 3. 关键：从池子中剔除已使用的行
            # 只要 A 或 B 的范围有重叠，就剔除，防止同一个片段被重复提取
            used_a_indices = set()
            used_b_indices = set()
            for seg in chain:
                for i in range(seg['pos_a'], seg['pos_a'] + seg['len']): used_a_indices.add(i)
                for i in range(seg['pos_b'], seg['pos_b'] + seg['len']): used_b_indices.add(i)
            
            new_remaining = []
            for m in remaining_matches:
                # 检查这个匹配是否占用了已经提取出的行
                m_a_range = set(range(m['pos_a'], m['pos_a'] + m['len']))
                m_b_range = set(range(m['pos_b'], m['pos_b'] + m['len']))
                
                if m_a_range.isdisjoint(used_a_indices) and m_b_range.isdisjoint(used_b_indices):
                    new_remaining.append(m)
            
            remaining_matches = new_remaining
            if not remaining_matches:
                break
                
        return all_scenes

# --- 使用示例 ---
def process_shuffled_scripts(script_a, script_b):
    # 1. 之前定义的 LSH + RapidFuzz(WRatio) 匹配，得到 raw_matches
    # 注意：这里的 score 建议用 fuzz.WRatio 以考虑词序
    # raw_matches = matcher.match(script_b) 
    return
    
    # 2. 实例化提取器
    # min_chain_score 设置为 300 意味着至少要有 3-4 个连续的 3 行窗口匹配（约 5-10 行对白）
    chainer = SceneChainer(raw_matches, min_chain_score=300)
    
    # 3. 提取所有大块链条
    scenes = chainer.extract_all_scenes()
    
    # 4. 打印结果
    for idx, scene in enumerate(scenes):
        print(f"--- 发现场次 {idx+1} (总分: {scene['total_score']}) ---")
        print(f"  在剧本 A 中的位置: {scene['a_range'][0]} - {scene['a_range'][1]} 行")
        print(f"  在剧本 B 中的位置: {scene['b_range'][0]} - {scene['b_range'][1]} 行")
        # 打印场次内的第一句对白确认
        print(f"  起始台词示例: {scene['segments'][0]['text_a'][:30]}...")
        print("-" * 40)

    return scenes
