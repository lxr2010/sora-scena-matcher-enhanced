from pydantic import BaseModel, TypeAdapter, model_validator
from pathlib import Path
import json

class Line(BaseModel):
    """
    {
        "character_id": "0xF",
        "voice_id": "0940010125V",
        "script_id": 49,
        "text": "おや、嬢ちゃんたちは……",
        "source_file": "C0100.txt",
        "context_prev": "",
        "context_next": "あなたが鉱山長さん？よかった、やっと見つけたわ。"
    }
    """
    character_id: str
    voice_id: str
    script_id: int
    text: str
    source_file: str
    context_prev: str
    context_next: str
    @property
    def scene_id(self):
        return self.voice_id[3:6]
    @property
    def scene_seq_id(self):
        return int(self.voice_id[6:10] or "-1")

class Conversation(BaseModel):
    lines: list[Line]
    def __len__(self) -> int:
        return len(self.lines)
    def __getitem__(self, index: int) -> Line:
        return self.lines[index]
    def __iter__(self):
        return iter(self.lines)

class RemakeCommand(BaseModel):
    """
    {
        "file": "F:\\code\\sora-script-test\\scena\\jp\\mp0000.py",
        "line": 9941,
        "column": 4,
        "type": "Command",
        "code": "Command('Cmd_text_00', [INT(10007), '<#E_0#M_0#B_0>', '何だ、エステル。', INT(10), 'どっか出かけんのか？'])",
        "normalized_args": "5,0,10007,<#E_0#M_0#B_0>,何だ、エステル。,10,どっか出かけんのか？",
        "command": "Cmd_text_00",
        "args": [
            10007,
            "何だ、エステル。どっか出かけんのか？"
        ],
        "line_corr": 9291
    }
    """
    file: str
    line: int
    column: int
    type: str
    code: str
    normalized_args: str
    command: str
    args: list
    line_corr: int | None

class RemakeLine(BaseModel):
    id: int 
    text: str
    remake_voice_id: int | None = None
    filebase: str
    lineno: int
    lineno_corr: int | None = None

    @model_validator(mode="before")
    @classmethod
    def handle_remake_commands(cls, data):
        if isinstance(data, dict):
            args = data.pop("args", None)
            if args:
                data["text"] = args[-1]
                if len(args) >= 3 and args[-3] == 11 and isinstance(args[-2], int):
                    data["remake_voice_id"] = args[-2]
                if len(args) >= 2 and args[-2] == 11 and isinstance(args[-1], int):
                    data["remake_voice_id"] = args[-1]
                    data["text"] = ""
            file = data.pop("file", None)
            if file:
                data["filebase"] = Path(file).stem
            line = data.pop("line", None)
            if line:
                data["lineno"] = line
            line_corr = data.pop("line_corr", None)
            if line_corr:
                data["lineno_corr"] = line_corr
        elif isinstance(data, RemakeCommand):
            args = data.args
            if args:
                data["text"] = args[-1]
                if len(args) >= 3 and args[-3] == 11 and isinstance(args[-2], int):
                    data["remake_voice_id"] = args[-2]
                if len(args) >= 2 and args[-2] == 11 and isinstance(args[-1], int):
                    data["remake_voice_id"] = args[-1]
                    data["text"] = ""
            file = data.file
            if file:
                data["filebase"] = Path(file).stem
            line = data.line
            if line:
                data["lineno"] = line
            line_corr = data.line_corr
            if line_corr:
                data["lineno_corr"] = line_corr
        return data

class RemakeConversation(BaseModel):
    lines: list[RemakeLine]
    def __len__(self) -> int:
        return len(self.lines)
    def __getitem__(self, index: int) -> RemakeLine:
        return self.lines[index]
    def __iter__(self):
        return iter(self.lines)

    

def test_lines():
    with open("script_data.json", "r") as f:
        # The JSON file is a list of objects, so we use TypeAdapter to validate it as a list[Line]
        adapter = TypeAdapter(list[Line])
        lines = adapter.validate_json(f.read())
        for line in lines:
            print(line)

def test_voice_id():
    voice_id = VoiceId(voice_id="0940010125V")
    print(voice_id.scene_id)
    print(voice_id.scene_seq_id)
    voice_empty = VoiceId(voice_id="")
    print(voice_empty.scene_id)
    print(voice_empty.scene_seq_id)

def test_remake_command():
    NEW_ID_START=50001
    with open("scena_data_jp_Command_sample.json", "r") as f:
        adapter = TypeAdapter(list[RemakeCommand])
        lines = adapter.validate_json(f.read())
        for line in lines:
            print(line)

def test_remake_line():
    NEW_ID_START=50001
    with open("scena_data_jp_Command.json", "r") as f:
        commands: list[dict] = json.load(f)
        for i, entry in enumerate(commands):
            remake_line = RemakeLine(id=NEW_ID_START + i, **entry)
            print(remake_line)


if __name__ == "__main__":
    # test_lines()
    # test_voice_id()
    # test_remake_command()
    test_remake_line()
