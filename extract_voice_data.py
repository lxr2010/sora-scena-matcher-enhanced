import os
import re
import json

# 配置
# 源目录：包含原始日文脚本的文件夹
SOURCE_DIR = r'SoraVoiceScripts\cn.fc\out.msg'
# 输出文件：保存提取数据的JSON文件
OUTPUT_FILE = 'voice_data.json'
OUTPUT_SCRIPT_FILE = 'script_data.json'
# 语音ID的正则表达式
VOICE_ID_PATTERN = re.compile(r'#(\d+V)')
# 控制字符的正则表达式，匹配 [xNN] 格式
CONTROL_CODE_PATTERN = re.compile(r'(\[|骸)xX][0-9a-fA-F]{2,}\]')
# 脚本文本ID的正则表达式
SCRIPT_ID_PATTERN = re.compile(r'#(\d+)J')

def clean_text(text):
    """清理文本中的语音ID和所有控制字符。"""
    # 移除语音ID
    text = VOICE_ID_PATTERN.sub('', text)

    # 处理 #2R...# 格式的注音
    def process_ruby_characters(t):
        # define regex of #2R(anything but #)#
        pattern = re.compile(r'#\d+R([^#]+)#')
        # iterately, record the matched text in pattern, and remove the matched pattern from t
        # we need to record the last position of the matched pattern, and put recorded text in the last position
        recorded = ""
        last_position = None
        while pattern.search(t):
            match = pattern.search(t)
            last_position = match.start()
            recorded += match.group(1)
            t = t[:match.start()] + t[match.end():]
        if last_position is not None:
            t = t[:last_position] + "（" + recorded + "）" + t[last_position:]
        return t

    text = process_ruby_characters(text)

    # Remove backslash escaping like \\x87
    text = re.sub(r'\\x[0-9a-fA-F]{2}', '', text)

    # 移除 [xNN] 格式的控制字符
    text = re.sub(r'\[[xX][0-9a-fA-F]{2}\]', '', text)
    # 移除文本中常见的其他非对话部分，例如口型和表情数据
    text = re.sub(r'#[0-9a-zA-Z]+', '', text)
    # 替换骸x01],骸x02],骸x03]等乱码数据为❤
    text = re.sub(r'骸x01]', '❤', text)
    text = re.sub(r'骸x02]', '❤', text)
    text = re.sub(r'骸x03]', '❤', text)
    return text.strip()

def parse_script_file(file_path):
    """解析单个脚本文件，提取对话数据。"""
    voice_entries = []
    try:
        with open(file_path, 'r', encoding='shift_jis', errors='backslashreplace') as f:
            lines = [line.strip() for line in f.readlines()]

        current_char_id = None
        i = 0
        while i < len(lines):
            line = lines[i]

            if line.startswith('ChrTalk'):
                # 下一行是角色ID
                if i + 1 < len(lines):
                    current_char_id = lines[i + 1]
            
            # 检查是否是包含语音ID的对话行
            match = VOICE_ID_PATTERN.search(line)
            if match and current_char_id:
                voice_id = match.group(1)

                # 检查脚本文本ID
                script_id_match = SCRIPT_ID_PATTERN.search(line)
                if script_id_match:
                    script_id = int(script_id_match.group(1))
                else:
                    script_id = -1
                
                # 处理换行符 [x01]
                dialogue_text = line
                # 增加处理骸x01]的情况
                while dialogue_text.endswith('[x01]') or dialogue_text.endswith('骸x01]'):
                    dialogue_text = dialogue_text[:-5] # 移除 '[x01]'
                    i += 1
                    if i < len(lines):
                        dialogue_text += lines[i]
                    else:
                        break

                cleaned_dialogue = clean_text(dialogue_text)

                if cleaned_dialogue:
                    voice_entries.append({
                        'character_id': current_char_id,
                        'voice_id': voice_id,
                        'script_id': script_id,
                        'text': cleaned_dialogue,
                        'source_file': os.path.basename(file_path)
                    })

            i += 1

    except Exception as e:
        print(f"Error processing file {file_path}: {e}")

    return voice_entries

def main():
    """主函数，遍历目录，处理文件并生成最终的JSON。"""
    all_voice_data = []
    source_folder = os.path.abspath(SOURCE_DIR)

    if not os.path.isdir(source_folder):
        print(f"Error: Source directory not found at '{source_folder}'")
        return

    print(f"Scanning files in '{source_folder}'...")

    # 文件名排序，确保处理顺序稳定
    file_list = sorted(os.listdir(source_folder))
    for filename in file_list:
        if filename.lower().endswith('.txt'):
            file_path = os.path.join(source_folder, filename)
            print(f"Processing {filename}...")
            extracted_data = parse_script_file(file_path)
            if extracted_data:
                all_voice_data.extend(extracted_data)

    # 按照script_id去重， 并输出为另一个JSON文件
    print("\nDeduplicating entries by script_id...")
    unique_scripts = {}
    for entry in all_voice_data:
        unique_scripts[entry['script_id']] = entry
    all_script_data = list(unique_scripts.values())
    # 重新排序以确保上下文正确
    all_script_data.sort(key=lambda x: x['script_id'])
    print(f"Deduplication complete. {len(all_script_data)} unique entries remaining.")

    # 添加上下文
    print("\nAdding context...")
    for i, entry in enumerate(all_script_data):
        entry['context_prev'] = all_script_data[i-1]['text'] if i > 0 else ""
        entry['context_next'] = all_script_data[i+1]['text'] if i < len(all_script_data) - 1 else ""

    # 保存到JSON文件
    output_path = os.path.abspath(OUTPUT_SCRIPT_FILE)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_script_data, f, ensure_ascii=False, indent=4)
    print(f"\nScript data saved to {output_path}")
    

    # 按voice_id去重
    print("\nDeduplicating entries by voice_id...")
    unique_voices = {}
    for entry in all_voice_data:
        unique_voices[entry['voice_id']] = entry
    all_voice_data = list(unique_voices.values())
    # 重新排序以确保上下文正确
    all_voice_data.sort(key=lambda x: x['voice_id'])
    print(f"Deduplication complete. {len(all_voice_data)} unique entries remaining.")

    # 添加上下文
    print("\nAdding context...")
    for i, entry in enumerate(all_voice_data):
        
        # 添加上一句上下文
        if i > 0:
            entry['context_prev'] = all_voice_data[i-1]['text']
        else:
            entry['context_prev'] = ""
            
        # 添加下一句上下文
        if i < len(all_voice_data) - 1:
            entry['context_next'] = all_voice_data[i+1]['text']
        else:
            entry['context_next'] = ""

    # 保存到JSON文件
    output_path = os.path.abspath(OUTPUT_FILE)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_voice_data, f, ensure_ascii=False, indent=4)

    print(f"\nExtraction complete. {len(all_voice_data)} voice entries found.")
    print(f"Data saved to {output_path}")

if __name__ == '__main__':
    # To run the full extraction, comment out or remove the test block below and uncomment the line below
    main()
    
    # Test cases for clean_text function
    # test_cases = [
    #     "#175207J#0020141021V#9B#26Z#40B#80Z７人の《蛇#2Rア#の#2Rン#使#2Rギ#徒#2Rス#》の１人！[x02][x03]",
    #     "#175208J#0020141022V#4B#23Z#67B#85Z《白面》のワイスマン……！[x02]",
    #     "ただの普通のテキスト",
    #     "Another test: 軌跡#2Rキセキ#",
    #     "Complex: 理#2Rリ#性#2Rセイ#を失っているな…",
    #     "No ruby: #12345VThis is a test.",
    #     "Mixed: これは軌跡#2Rキセキ#のテストです。"
    # ]

    # print("--- Testing clean_text function ---")
    # for i, test_str in enumerate(test_cases):
    #     print(f"Test Case #{i+1}:")
    #     print(f"  Original:  {test_str}")
    #     cleaned = clean_text(test_str)
    #     print(f"  Cleaned:   {cleaned}")
    #     print("---")
