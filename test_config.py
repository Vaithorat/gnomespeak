import json

with open('server/config.json', 'r') as f:
    data = json.load(f)

ed = data.get('encrypted_data', {})
for key in ['openai_api_key', 'gemini_api_key', 'opencode_api_key', 'openrouter_api_key']:
    val = ed.get(key, '')
    if val:
        print(f'{key}: SET ({len(val)} chars)')
    else:
        print(f'{key}: EMPTY')
