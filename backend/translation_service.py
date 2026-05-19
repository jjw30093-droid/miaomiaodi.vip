import os
import json
import re

class TranslationService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(TranslationService, cls).__new__(cls, *args, **kwargs)
            cls._instance._init()
        return cls._instance

    def _init(self):
        # Determine paths relative to this file
        base_dir = os.path.dirname(os.path.abspath(__file__))
        team_mapping_path = os.path.join(base_dir, "team_zh.json")
        player_mapping_path = os.path.join(base_dir, "player_zh.json")

        self.team_dict = {}
        self.player_dict = {}
        self.md_pattern = None
        self.combined_dict = {}

        try:
            if os.path.exists(team_mapping_path):
                with open(team_mapping_path, 'r', encoding='utf-8') as f:
                    self.team_dict = json.load(f)
        except Exception as e:
            print(f"Error loading team mapping: {e}")

        try:
            if os.path.exists(player_mapping_path):
                with open(player_mapping_path, 'r', encoding='utf-8') as f:
                    self.player_dict = json.load(f)
        except Exception as e:
            print(f"Error loading player mapping: {e}")

        self._compile_pattern()

    def _compile_pattern(self):
        self.combined_dict = {**self.team_dict, **self.player_dict}
        if self.combined_dict:
            # Sort keys by length descending to match longest phrases first (e.g., Bukayo Saka before Saka)
            escaped_keys = [re.escape(k) for k in sorted(self.combined_dict.keys(), key=len, reverse=True)]
            # using \b for word boundaries. 
            pattern_str = r'\b(' + '|'.join(escaped_keys) + r')\b'
            self.md_pattern = re.compile(pattern_str)

    def reload(self):
        self._init()

    def translate_team(self, team_name: str) -> str:
        if not team_name:
            return team_name
        return self.team_dict.get(team_name, team_name)

    def translate_markdown(self, content: str) -> str:
        if not content or not self.md_pattern:
            return content
        
        def replace_match(match):
            original = match.group(0)
            return self.combined_dict.get(original, original)
            
        return self.md_pattern.sub(replace_match, content)

# Singleton instance
translator = TranslationService()
