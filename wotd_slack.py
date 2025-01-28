import datetime
import os
import pathlib
import re
from typing import (
    Dict,
    List
)
from urllib import parse

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

def collect_wotd_nik() -> Dict:
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

def collect_wotd_wikt() -> List[Dict]:
    url = os.environ['WORD_SOURCE_URL']
    tld = parse.urlparse(url=url)
    tod = datetime.datetime.today()
    dom = get_dom(f'{url}/{tod:%Y/%B_%-d}')

    wotd_elem = dom.xpath('.//table[@class="wotd-container"]')[0]

    word_elem = wotd_elem.xpath('.//span[@id="WOTD-rss-title"]/parent::*')[0]
    pos = word_elem.xpath('./parent::*/parent::*/i')[0].text
    word = word_elem.xpath('./span')[0].text
    word_url = '{}://{}{}'.format(tld.scheme, tld.netloc, word_elem.attrib.get('href'))

    # Get definition
    definitions = [''.join(x.itertext()) for x in wotd_elem.xpath('.//div[@id="WOTD-rss-description"]/ol[1]/li')]

    # Get more detail
    worddom = get_dom(word_url)

    # Get pronunciation
    pron_section = worddom.xpath('.//div[contains(@class, "mw-heading3")]/h3[starts-with(text(), "Pronunciation")]/parent::*/following-sibling::ul')[0]
    pron = word
    for elem in pron_section.xpath('./li'):
        full_text = ''.join([x for x in elem.itertext()]).strip()
        if 'American' in full_text:
            pron = full_text[full_text.index(':') + 1:]

    # Get Etymology
    etys = []
    ety_elems = worddom.xpath('.//div[contains(@class, "mw-heading3")]/h3[starts-with(text(), "Etymology")]/parent::*/following-sibling::*')
    for elem in ety_elems:
        elem_type = elem.tag
        if elem_type not in ['p', 'ul']:
            break
        if elem_type == 'ul':
            sub_elems = elem.xpath('./li')
            for se in sub_elems:
                ety_text = ''.join(x for x in se.itertext()).strip()
                # Clear of refs (because Slack can't render it well)
                ety_text = re.sub(r'\[\d+\]', '', ety_text)
                etys.append(' - ' + ety_text)
        else:
            ety_text = ''.join(x for x in elem.itertext()).strip()
            # Clear of refs (because Slack can't render it well)
            ety_text = re.sub(r'\[\d+\]', '', ety_text)

            etys.append(ety_text)

    return build_blocks(
        word=word,
        pos=pos,
        pronunciation=pron,
        definitions=definitions,
        etymologies=etys
    )


def build_blocks(word: str, pos: str, pronunciation: str, definitions: List[str], etymologies: List[str]) -> List[Dict]:
    # Build the message block
    tod = datetime.datetime.today()

    _blocks = [
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
                "text": f"*{word}* _`{pos}`_",
            }
        }, {
            "type": "context",
            "elements": [
                {
                    "type": "plain_text",
                    "text": pronunciation,
                    "emoji": True
                }
            ]
        }
    ]

    # Build definitions
    for i, d in enumerate(definitions):
        _blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f'{i + 1}. {d}',
            }
        })
    _blocks.append({'type': 'divider'})

    if len(etymologies) > 0:
        _blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ':sparkles: *Etymology* :sparkles:',
            }
        })
    # Build etymology
    for e in etymologies:
        _blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": e
                }
            ]
        })

    _blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": os.environ['MESSAGE'],
        }
    })

    return _blocks


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

    blocks = collect_wotd_wikt()
    res = send_blocks_to_slack(blocks=blocks)
    logger.debug(f'HTTP response code from Slack: {res.status_code}')
