import requests
from utils import append_to_log, get_finance_token
BASE_URL = 'https://cjremmett.com/finance-api/get-earnings-call-transcript'


def get_earnings_call_transcript(ticker: str, year: int, quarter: int) -> str:
    try:
        url = BASE_URL + f'?ticker={ticker}&year={year}&quarter={quarter}'
        headers = {'token': get_finance_token()}
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            raise Exception(f"Failed to fetch data: {response.status_code} - {response.text}")
        
        return (response.json())['transcript']
    except Exception as e:
        append_to_log('ERROR', 'Exception thrown in get_earnings_call_transcript: ' + repr(e))
        return ''