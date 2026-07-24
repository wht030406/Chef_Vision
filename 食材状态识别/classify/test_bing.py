import requests, re

q = "burnt tomato scrambled eggs overcooked"
url = "https://www.bing.com/images/search?q=" + requests.utils.quote(q) + "&form=HDRSC2&first=1"
r = requests.get(url, timeout=10, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
})
print("status:", r.status_code, "length:", len(r.text))

# 打印前2000字符找规律
print("\n--- 前2000字符 ---")
print(r.text[:2000])
print("\n--- 含'http'的行 ---")
for line in r.text.split('\n'):
    if 'http' in line and ('jpg' in line or 'jpeg' in line or 'png' in line):
        print(line[:200])
        break
