import pytest
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intent_parser import IntentParser, SENTENCE_ENDINGS, MAX_CHUNK_CHARS


class TestSentenceChunking:
    def test_sentence_endings_pattern(self):
        assert SENTENCE_ENDINGS.search("Hello world. ")
        assert SENTENCE_ENDINGS.search("Hello world! ")
        assert SENTENCE_ENDINGS.search("Hello world? ")
        assert SENTENCE_ENDINGS.search("End\n")
        assert not SENTENCE_ENDINGS.search("Hello world")
        assert not SENTENCE_ENDINGS.search("Hello world.")

    def test_max_chunk_chars(self):
        assert MAX_CHUNK_CHARS == 500

    def test_chunking_single_sentence(self):
        import re
        text = "Hello world. "
        match = list(SENTENCE_ENDINGS.finditer(text))
        assert len(match) == 1

    def test_chunking_multiple_sentences(self):
        import re
        text = "First sentence. Second sentence. "
        match = list(SENTENCE_ENDINGS.finditer(text))
        assert len(match) == 2


class TestRegexRules:
    def setup_method(self):
        self.parser = IntentParser.__new__(IntentParser)
        self.parser.sessions = {}
        self.parser.config = None
        self.parser.default_client = None
        self.parser.default_provider = None
        self.parser.env_model = None

    def test_open_prefix(self):
        result = self.parser._parse_with_rules("open notepad")
        assert result["action"] == "open_app"
        assert result["params"]["name"] == "notepad"

    def test_launch_prefix(self):
        result = self.parser._parse_with_rules("launch chrome")
        assert result["action"] == "open_app"
        assert result["params"]["name"] == "chrome"

    def test_start_prefix(self):
        result = self.parser._parse_with_rules("start spotify")
        assert result["action"] == "open_app"
        assert result["params"]["name"] == "spotify"

    def test_run_prefix(self):
        result = self.parser._parse_with_rules("run calculator")
        assert result["action"] == "open_app"
        assert result["params"]["name"] == "calculator"

    def test_open_url(self):
        result = self.parser._parse_with_rules("open youtube.com")
        assert result["action"] == "browser_navigate"
        assert result["params"]["url"] == "youtube.com"

    def test_go_to_url(self):
        result = self.parser._parse_with_rules("go to github.com")
        assert result["action"] == "browser_navigate"
        assert result["params"]["url"] == "github.com"

    def test_go_to_path(self):
        result = self.parser._parse_with_rules("go to C:\\Users")
        assert result["action"] == "navigate"
        assert result["params"]["path"] == "c:\\users"

    def test_play_youtube(self):
        result = self.parser._parse_with_rules("play lofi hip hop")
        assert result["action"] == "yt_play"
        assert result["params"]["query"] == "lofi hip hop"

    def test_play_on_youtube(self):
        result = self.parser._parse_with_rules("play despacito on youtube")
        assert result["action"] == "yt_play"
        assert result["params"]["query"] == "despacito"

    def test_search_google(self):
        result = self.parser._parse_with_rules("search for python tutorials")
        assert result["action"] == "browser_search"
        assert result["params"]["query"] == "python tutorials"
        assert result["params"]["engine"] == "google"

    def test_search_bing(self):
        result = self.parser._parse_with_rules("search for news on bing")
        assert result["action"] == "browser_search"
        assert result["params"]["query"] == "news"
        assert result["params"]["engine"] == "bing"

    def test_list_dir(self):
        result = self.parser._parse_with_rules("list C:\\Users")
        assert result["action"] == "list_dir"
        assert result["params"]["path"] == "c:\\users"

    def test_show_dir(self):
        result = self.parser._parse_with_rules("show downloads")
        assert result["action"] == "list_dir"
        assert result["params"]["path"] == "downloads"

    def test_open_folder_via_prefix(self):
        result = self.parser._parse_with_rules("open folder C:\\Projects")
        assert result["action"] == "navigate"
        assert result["params"]["path"] == "C:\\Projects"

    def test_open_file_via_prefix(self):
        result = self.parser._parse_with_rules("open file C:\\test.txt")
        assert result["action"] == "navigate"
        assert result["params"]["path"] == "C:\\test.txt"

    def test_send_email(self):
        result = self.parser._parse_with_rules("send email to bob@example.com with subject Hello and body Test")
        assert result["action"] == "send_email"
        assert result["params"]["to"] == "bob@example.com"
        assert result["params"]["subject"] == "hello"
        assert result["params"]["body"] == "test"

    def test_create_file(self):
        result = self.parser._parse_with_rules("create file test.txt with content Hello")
        assert result["action"] == "create_file"
        assert result["params"]["path"] == "test.txt"
        assert result["params"]["content"] == "hello"

    def test_create_folder(self):
        result = self.parser._parse_with_rules("create folder new_dir")
        assert result["action"] == "create_folder"
        assert result["params"]["path"] == "new_dir"

    def test_delete_file(self):
        result = self.parser._parse_with_rules("delete test.txt")
        assert result["action"] == "delete"
        assert result["params"]["path"] == "test.txt"

    def test_copy_file(self):
        result = self.parser._parse_with_rules("copy a.txt to b.txt")
        assert result["action"] == "copy"
        assert result["params"]["source"] == "a.txt"
        assert result["params"]["destination"] == "b.txt"

    def test_move_file(self):
        result = self.parser._parse_with_rules("move a.txt to folder")
        assert result["action"] == "move"
        assert result["params"]["source"] == "a.txt"
        assert result["params"]["destination"] == "folder"

    def test_fallback_to_app_launch(self):
        result = self.parser._parse_with_rules("random gibberish text")
        assert result["action"] == "open_app"
        assert result["params"]["name"] == "random gibberish text"

    def test_url_detection_youtube(self):
        assert self.parser._looks_like_url("youtube.com")
        assert self.parser._looks_like_url("youtube")
        assert self.parser._looks_like_url("github.com")
        assert self.parser._looks_like_url("reddit.com")

    def test_url_detection_new_sites(self):
        assert self.parser._looks_like_url("mysite.org")
        assert self.parser._looks_like_url("example.co.uk")
        assert self.parser._looks_like_url("app.io")

    def test_not_url(self):
        assert not self.parser._looks_like_url("notepad")
        assert not self.parser._looks_like_url("hello world")
