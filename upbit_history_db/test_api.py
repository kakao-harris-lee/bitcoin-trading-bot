"""
업비트 API 동작 테스트
"""

import requests

# 1분 봉 API 테스트
url = "https://api.upbit.com/v1/candles/minutes/1"

print("첫 번째 요청:")
response1 = requests.get(url, params={'market': 'KRW-BTC', 'count': 3})
data1 = response1.json()

for item in data1:
    print(f"  {item['candle_date_time_kst']} (UTC: {item['candle_date_time_utc']})")

print(f"\n마지막 캔들: {data1[-1]['candle_date_time_kst']}")
print(f"마지막 캔들 UTC: {data1[-1]['candle_date_time_utc']}")

# KST 시간으로 두 번째 요청
print(f"\n두 번째 요청 (to={data1[-1]['candle_date_time_kst']}):")
response2 = requests.get(url, params={
    'market': 'KRW-BTC',
    'count': 3,
    'to': data1[-1]['candle_date_time_kst']
})
data2 = response2.json()

for item in data2:
    print(f"  {item['candle_date_time_kst']} (UTC: {item['candle_date_time_utc']})")

# UTC 시간으로 세 번째 요청
print(f"\n세 번째 요청 (to={data1[-1]['candle_date_time_utc']}):")
response3 = requests.get(url, params={
    'market': 'KRW-BTC',
    'count': 3,
    'to': data1[-1]['candle_date_time_utc']
})
data3 = response3.json()

for item in data3:
    print(f"  {item['candle_date_time_kst']} (UTC: {item['candle_date_time_utc']})")
