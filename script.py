from typing import Collection
from pathlib import Path
from os import system
from os.path import exists
import re
import csv
from bs4 import BeautifulSoup

import numpy as np
import requests

CSV_PATH = "biglist.csv"
ANKI_MEDIA = ".local/share/Anki2/User 1/collection.media/"


class Note:
    def __init__(self, *args):
        args = args[0]
        self.headword = args[0]
        self.definition = args[1]
        self.example = args[2]
        self.video_url = args[3]
        self.video_title = args[4]
        self.url = args[5]
        self.tags = [normalize_tag(x) for x in args[6]]

    def __str__(self):
        tag_str = " ".join(self.tags)

        joined = ";".join(
            [
                normalize_csv(self.headword),
                normalize_csv(self.definition),
                normalize_csv(self.example),
                f"[sound:{video_filename(self.video_url)}]",
                normalize_csv(self.video_url),
                normalize_csv(self.video_title),
                normalize_csv(self.url),
                normalize_csv(tag_str),
            ]
        )

        return joined


def get_page(url):
    html = requests.get(url).text
    page = BeautifulSoup(html, "lxml")
    return page


def get_definitions(url, tags):
    page = get_page(url)
    notes = []
    headings = [page.find("h1")] + page.find_all("h2")
    if not page.find_all(itemprop="video"):
        return notes
    for heading in headings:
        headword = heading.text
        tags += [x.text for x in heading.find_next_siblings("span")]
        first_p = heading.find_next_sibling("p")
        def_string = re.findall("</b> (.*?)<br/>", str(first_p))
        if def_string:
            definition = def_string[0]
        else:
            definition = ""
        italics = first_p.find("i")
        if italics is not None:
            example = italics.text
        else:
            example = ""
        video_div = first_p.find_next(itemprop="video")
        video_url = video_div.find(itemprop="contentURL")["content"]
        video_title = re.findall("(<i>.*?) <br/>", str(video_div))[0]
        notes.append(
            Note([headword, definition, example, video_url, video_title, url, tags])
        )
    return notes


def normalize_tag(string):
    return string.replace(" ", "_")


def normalize_csv(string):
    doubled_quotes = string.replace('"', '""')
    return f'"{doubled_quotes}"'


def video_filename(url):
    end = re.findall("signbsl.com/(.*)", url)[0]
    return end.replace("/", "_")


def frequency(word):
    word_file = "frequency.txt"
    reg = re.compile(f"^(\\d+) {word}$", re.MULTILINE)
    with open(word_file, "r") as file:
        filetext = file.read()
    results = reg.findall(filetext)
    if results:
        return int(results[0])
    return 10000


def word_list():
    page = get_page("https://www.signbsl.com/gcse-vocabulary")
    notes = []
    for category in page.find_all("h3"):
        pages = [
            "https://signbsl.com" + x["href"]
            for x in category.find_parent().find_all("a")
        ]
        for page in pages:
            print("Contacting ", page)
            notes += get_definitions(page, [category.text])
    write_csv(CSV_PATH, notes)


def write_csv(filename: str, notes: list[Note]) -> None:
    with open(filename, "w") as file:
        file.writelines([str(note) + "\n" for note in notes])

def sort_and_write_csv(filename: str, notes: list[Note]) -> None:
    """Sorts notes in-place by English word frequency, and then writes to csv
    (replaces functionality of write_csv function from repo this is forked from)
    """
    notes.sort(key=lambda note: frequency(note.headword))
    write_csv(filename, notes)

def convert_video(url):
    temp = Path("/tmp/")
    filename = video_filename(url)
    dest = Path.home() / Path(ANKI_MEDIA)
    if exists(dest / filename):
        print("Already converted", dest / filename)
        return
    response = requests.get(url)
    with open(f"{temp / filename}", mode="wb") as file:
        file.write(response.content)
    command = (
        f'ffmpeg -i "{temp / filename}" -vcodec libx265 -crf 32 "{dest / filename}"'
    )
    system(command)


def download_videos(csv_path):
    notes = read_csv(csv_path)
    for note in notes:
        convert_video(note.video_url)


def read_csv(path):
    notes = []
    with open(path) as file:
        reader = csv.reader(file, delimiter=";")
        for row in reader:
            tags = row[7].split(" ")
            # cut out the fourth item (see Note __str__ function)
            row = row[0:3] + row[4:7] + [tags]
            notes.append(Note(row))
    return notes


def add_signs(signs, tags, output):
    notes = []
    for sign in signs:
        notes += get_definitions("https://www.signbsl.com/sign/" + sign, tags)
    write_csv(output, notes)


def sort_notes_by_tag(
    custom_tag_order: Collection[str],
    notes: list[Note],
    batch_limit: int,
    shuffle_within_tags: bool,
) -> list[Note]:
    """Sort notes by tag, using custom tag order.
    Only take batch_limit words from each tag before moving onto next.
    Keep cycling through the given tag list extracting batches until none of any listed tag remains.
    Then assign any remaining words not covered by supplied tags.

    Can cope fine with overlapping tags.
    """

    tracked_notes = [{'selected': False, 'note': note} for note in notes]
    
    notes_by_tag = {}
    for note in tracked_notes:
        for tag in note['note'].tags:
            if tag not in notes_by_tag:
                notes_by_tag[tag] = []
            notes_by_tag[tag].append(note)
    
    def _add_note(note_list, tracked_note):
        if tracked_note['selected']:
            return False
        
        note_list.append(tracked_note['note'])
        tracked_note['selected'] = True
        return True
    
    sorted_notes = []
    spent_tags = set()
    while len(spent_tags) < len(custom_tag_order):
        for tag in custom_tag_order:
            if tag in spent_tags:
                continue

            notes_with_tag = notes_by_tag[tag]
            if shuffle_within_tags:
                traversal_order = np.random.choice(len(notes_with_tag), size=len(notes_with_tag), replace=False)
            else:
                traversal_order = range(len(notes_with_tag))
            counter = 0
            for idx in traversal_order:
                if _add_note(sorted_notes, notes_with_tag[idx]):
                    counter += 1
                if counter >= batch_limit:
                    break

            if counter < batch_limit:
                spent_tags.add(tag)

    for note in tracked_notes:
        if _add_note(sorted_notes, note):
            print(f'Note {note['note'].headword} was not covered by provided tag order, so putting at end.')

    return sorted_notes

def reorder_csv_by_tag(
    in_path: str,
    out_path: str,
    custom_tag_order: Collection[str],
    batch_limit: int,
    shuffle_within_tags: bool = False,
) -> None:
    notes = read_csv(in_path)
    sorted_notes = sort_notes_by_tag(custom_tag_order, notes, batch_limit, shuffle_within_tags=shuffle_within_tags)

    write_csv(out_path, sorted_notes)