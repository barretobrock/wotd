import datetime
import os
import pathlib
from typing import (
    Dict,
    List
)

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from loguru import logger
from lxml import etree
import requests
from slack_sdk import WebClient


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0',
}


def get_dom(url: str) -> etree.Element:
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, 'html.parser')
    return etree.HTML(str(soup))


def collect_pron(word: str) -> str:
    # Try to get pronunciation
    pdom = get_dom(f'https://www.dictionary.com/browse/{word}')

    pron = []
    pron_elem = pdom.xpath('.//div[@data-type="pronunciation-toggle"]/p')[0]
    for pe in pron_elem.itertext():
        text_strip = pe.strip()
        if text_strip == '':
            continue
        pron.append(text_strip)
    for pe in pron_elem.iter():
        text_strip = pe.text.strip()
        if text_strip == '':
            continue
        if pe.tag == 'strong':
            if text_strip in pron:
                pron[pron.index(text_strip)] = f'{text_strip.upper()}'
    if len(pron) == 0:
        raise ValueError('No pronunciation elements retrieved!')
    return ''.join(pron)


def collect_wotd() -> Dict:
    dom = get_dom(os.environ['WORD_SOURCE_URL'])

    wotd_elem = dom.xpath('.//div[@id="wotd"]/div[@class="content_column"]')[0]

    word = wotd_elem.xpath('./h1/a')[0].text
    pos, definition = [x for x in wotd_elem.xpath('.//div[@id="define"]/div/ul/li')[0].itertext()]

    try:
        pron = collect_pron(word=word)
    except Exception as e:
        logger.error(f'Couldn\'t capture pronunciation: {e}')
        pron = word

    return {
        'word': word,
        'pronunciation': pron,
        'def': definition,
        'part_of_speech': pos,
        'origin': wotd_elem.xpath('.//p[@class="note"]')[0].text
    }


def build_blocks(wotd_dict: Dict) -> List[Dict]:
    # Build the message block
    tod = datetime.datetime.today()
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Word of the Day for {tod:%A the %-dpthst of %B, in the %Yndth year of 2020}",
                "emoji": True
            }
        }, {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*{word}*\t\t*`{pronunciation}`*".format(**wotd_dict),
            }
        }, {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*`{part_of_speech}`* {def}".format(**wotd_dict),
            }
        }, {
            "type": "context",
            "elements": [
                {
                    "type": "plain_text",
                    "text": wotd_dict['origin'],
                    "emoji": True
                }
            ]
        }, {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": os.environ['MESSAGE'],
            }
        },

    ]


def send_blocks_to_slack(blocks: List[Dict]):
    return bot_client.chat_postMessage(
        channel=os.environ['SLACK_CHANNEL_ID'],
        text='WOTD incoming!',
        blocks=blocks
    )


if __name__ == '__main__':
    ROOT = pathlib.Path(__file__).parent
    load_dotenv(dotenv_path=ROOT.joinpath('.env'))
    bot_client = WebClient(token=os.environ['SLACK_BOT_TOKEN'])

    wotd = collect_wotd()
    blocks = build_blocks(wotd_dict=wotd)
    res = send_blocks_to_slack(blocks=blocks)
    logger.debug(f'HTTP response code from Slack: {res.status_code}')
