import pytest
import os
import sys
import tempfile
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intent_parser import IntentParser, SENTENCE_ENDINGS, MAX_CHUNK_CHARS, MAX_TOOL_RESULT_CHARS


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

    def test_open_browser_and_search(self):
        result = self.parser._parse_with_rules("open browser and search for python tutorials")
        assert result["action"] == "browser_search"
        assert result["params"]["query"] == "python tutorials"
        assert result["params"]["engine"] == "google"

    def test_open_youtube_and_search(self):
        result = self.parser._parse_with_rules("open YouTube and search for cbr 1000 rr")
        assert result["action"] == "yt_search"
        assert result["params"]["query"] == "cbr 1000 rr"

    def test_open_youtube_search_and_play_first_video(self):
        result = self.parser._parse_with_rules(
            "open YouTube and search for the office and play the first video that comes up"
        )
        assert result["action"] == "yt_play"
        assert result["params"]["query"] == "the office"

    def test_open_browser_open_youtube_and_search(self):
        result = self.parser._parse_with_rules("open the browser open YouTube and search for cbr 1000 rr")
        assert result["action"] == "yt_search"
        assert result["params"]["query"] == "cbr 1000 rr"

    def test_open_browser_open_youtube_search_and_play_first_video(self):
        result = self.parser._parse_with_rules(
            "open the browser open YouTube and search for the office and play the first video that comes up"
        )
        assert result["action"] == "yt_play"
        assert result["params"]["query"] == "the office"

    def test_go_to_youtube_and_search(self):
        result = self.parser._parse_with_rules("go to YouTube and search Taarak Mehta")
        assert result["action"] == "yt_search"
        assert result["params"]["query"] == "taarak mehta"

    def test_open_browser_go_to_youtube_and_play_first_video(self):
        result = self.parser._parse_with_rules(
            "open the browser go to YouTube and play the first video that is there"
        )
        assert result["action"] == "yt_play_first_result"
        assert result["params"] == {}

    def test_play_first_video_uses_last_youtube_search(self):
        result = self.parser._parse_with_rules("play the first video that is")
        assert result["action"] == "yt_play_first_result"
        assert result["params"] == {}

    def test_normalize_command_text_strips_polite_wrapper(self):
        assert self.parser._normalize_command_text(
            "please open youtube and search for cbr 1000 rr"
        ) == "open youtube and search for cbr 1000 rr"

    def test_normalize_command_text_handles_stt_wrapper(self):
        assert self.parser._normalize_command_text(
            "what you to open YouTube and search for the office"
        ) == "open YouTube and search for the office"

    def test_normalize_command_text_handles_open_of_youtube(self):
        assert self.parser._normalize_command_text(
            "open of youtube and search for the office"
        ) == "open youtube and search for the office"

    def test_open_browser_and_play(self):
        result = self.parser._parse_with_rules("open browser and play lofi hip hop")
        assert result["action"] == "yt_play"
        assert result["params"]["query"] == "lofi hip hop"

    def test_open_browser_and_go_to(self):
        result = self.parser._parse_with_rules("open browser and go to github.com")
        assert result["action"] == "browser_navigate"
        assert result["params"]["url"] == "github.com"

    def test_set_volume_to_full(self):
        result = self.parser._parse_with_rules("turn the volume to full")
        assert result["action"] == "set_volume"
        assert result["params"]["level"] == 100

    def test_set_volume_to_number(self):
        result = self.parser._parse_with_rules("set volume to 25%")
        assert result["action"] == "set_volume"
        assert result["params"]["level"] == 25

    def test_volume_up_rule(self):
        result = self.parser._parse_with_rules("make it louder")
        assert result["action"] == "volume_up"

    def test_lower_volume_to_number(self):
        result = self.parser._parse_with_rules("lower volume to 20")
        assert result["action"] == "set_volume"
        assert result["params"]["level"] == 20

    def test_increase_volume_to_number(self):
        result = self.parser._parse_with_rules("increase the volume to 80%")
        assert result["action"] == "set_volume"
        assert result["params"]["level"] == 80

    def test_mute_volume_rule(self):
        result = self.parser._parse_with_rules("mute the volume")
        assert result["action"] == "volume_mute"

    def test_bluetooth_on_rule(self):
        result = self.parser._parse_with_rules("turn bluetooth on")
        assert result["action"] == "control_bluetooth"
        assert result["params"]["action"] == "on"

    def test_bluetooth_status_rule(self):
        result = self.parser._parse_with_rules("bluetooth status")
        assert result["action"] == "control_bluetooth"
        assert result["params"]["action"] == "status"

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


class _FakeAsyncStream:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration


def _make_stream_chunk(content=None, finish_reason=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def _make_tool_call_delta(index=0, tool_id="tc_1", name=None, arguments=None):
    function = None
    if name is not None or arguments is not None:
        function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=tool_id, function=function)


class TestAgentStreaming:
    def _make_parser(self):
        config = MagicMock()
        config.data = {}
        config.get_secret.return_value = None
        return IntentParser(config)

    @pytest.mark.asyncio
    async def test_agent_stream_returns_partial_text_on_length_finish(self):
        parser = self._make_parser()
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_FakeAsyncStream([
            _make_stream_chunk(content="First sentence. Second chunk", finish_reason="length"),
        ]))

        chunks = [
            chunk
            async for chunk in parser._parse_with_agent_stream(
                "say hello", executor=None, ask_callback=None, client=client, session_id="s1"
            )
        ]

        assert chunks == [
            {"type": "chunk", "content": "First sentence. "},
            {"type": "chunk", "content": "Second chunk"},
            {"type": "final", "result": {"success": True, "message": "First sentence. Second chunk"}},
        ]

    @pytest.mark.asyncio
    async def test_agent_stream_returns_filtered_error_without_partial_text(self):
        parser = self._make_parser()
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=_FakeAsyncStream([
            _make_stream_chunk(content=None, finish_reason="content_filter"),
        ]))

        chunks = [
            chunk
            async for chunk in parser._parse_with_agent_stream(
                "blocked", executor=None, ask_callback=None, client=client
            )
        ]

        assert chunks == [
            {"type": "final", "result": {"success": False, "message": "AI provider content filtered"}},
        ]

    @pytest.mark.asyncio
    async def test_agent_stream_truncates_tool_result_in_session_history(self):
        parser = self._make_parser()
        executor = AsyncMock()
        executor.execute_tool.return_value = {"success": True, "message": "x" * (MAX_TOOL_RESULT_CHARS + 50)}

        first_stream = _FakeAsyncStream([
            _make_stream_chunk(tool_calls=[
                _make_tool_call_delta(index=0, tool_id="tc_1", name="list_dir", arguments='{"path":"Desktop"}'),
            ], finish_reason="tool_calls"),
        ])
        second_stream = _FakeAsyncStream([
            _make_stream_chunk(content="Done.", finish_reason="stop"),
        ])

        client = MagicMock()
        client.chat.completions.create = AsyncMock(side_effect=[first_stream, second_stream])

        chunks = [
            chunk
            async for chunk in parser._parse_with_agent_stream(
                "list desktop", executor=executor, ask_callback=None, client=client, session_id="s1"
            )
        ]

        assert chunks[-1] == {"type": "final", "result": {"success": True, "message": "Done."}}
        assert chunks[0]["type"] == "tool_result"

        stored = parser.sessions["s1"]
        tool_entries = [entry for entry in stored if entry.get("role") == "tool"]
        assert len(tool_entries) == 1
        assert tool_entries[0]["content"].endswith("...(truncated)")
        assert len(tool_entries[0]["content"]) == MAX_TOOL_RESULT_CHARS + len("...(truncated)")

        first_call_messages = client.chat.completions.create.await_args_list[0].kwargs["messages"]
        assert first_call_messages[0]["role"] == "system"
        assert "Windows PC assistant" in first_call_messages[0]["content"]


class TestDeterministicBypass:
    def _make_configured_parser(self):
        config = MagicMock()
        config.data = {}
        config.get_secret.side_effect = lambda key: "test-key" if key == "openai_api_key" else None
        return IntentParser(config)

    @pytest.mark.asyncio
    async def test_parse_bypasses_agent_for_absolute_volume(self):
        parser = self._make_configured_parser()
        parser._parse_with_agent = AsyncMock()

        executor = AsyncMock()
        executor.execute.return_value = {"success": True, "message": "Volume set to 100%"}

        result = await parser.parse("turn the volume to full", executor=executor)

        executor.execute.assert_awaited_once_with({"action": "set_volume", "params": {"level": 100}})
        parser._parse_with_agent.assert_not_called()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_parse_stream_bypasses_agent_for_absolute_volume(self):
        parser = self._make_configured_parser()
        parser._parse_with_agent_stream = AsyncMock()

        executor = AsyncMock()
        executor.execute.return_value = {"success": True, "message": "Volume set to 100%"}

        chunks = [
            chunk
            async for chunk in parser.parse_stream("turn the volume to full", executor=executor)
        ]

        executor.execute.assert_awaited_once_with({"action": "set_volume", "params": {"level": 100}})
        parser._parse_with_agent_stream.assert_not_called()
        assert chunks == [{"type": "final", "result": {"success": True, "message": "Volume set to 100%"}}]

    @pytest.mark.asyncio
    async def test_parse_bypasses_agent_for_browser_search(self):
        parser = self._make_configured_parser()
        parser._parse_with_agent = AsyncMock()

        executor = AsyncMock()
        executor.execute.return_value = {"success": True, "message": "Opened search"}

        result = await parser.parse("open browser and search for python tutorials", executor=executor)

        executor.execute.assert_awaited_once_with({
            "action": "browser_search",
            "params": {"query": "python tutorials", "engine": "google"},
        })
        parser._parse_with_agent.assert_not_called()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_parse_bypasses_agent_for_youtube_play(self):
        parser = self._make_configured_parser()
        parser._parse_with_agent = AsyncMock()

        executor = AsyncMock()
        executor.execute.return_value = {"success": True, "message": "Playing video"}

        result = await parser.parse("open browser and play lofi hip hop", executor=executor)

        executor.execute.assert_awaited_once_with({
            "action": "yt_play",
            "params": {"query": "lofi hip hop"},
        })
        parser._parse_with_agent.assert_not_called()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_parse_bypasses_agent_for_explicit_app_launch(self):
        parser = self._make_configured_parser()
        parser._parse_with_agent = AsyncMock()

        executor = AsyncMock()
        executor.execute.return_value = {"success": True, "message": "Opened notepad"}

        result = await parser.parse("open notepad", executor=executor)

        executor.execute.assert_awaited_once_with({
            "action": "open_app",
            "params": {"name": "notepad"},
        })
        parser._parse_with_agent.assert_not_called()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_parse_bypasses_agent_for_list_dir(self):
        parser = self._make_configured_parser()
        parser._parse_with_agent = AsyncMock()

        executor = AsyncMock()
        executor.execute.return_value = {"success": True, "message": "Listed directory"}

        result = await parser.parse("show downloads", executor=executor)

        executor.execute.assert_awaited_once_with({
            "action": "list_dir",
            "params": {"path": "downloads"},
        })
        parser._parse_with_agent.assert_not_called()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_parse_uses_agent_for_unmatched_text(self):
        parser = self._make_configured_parser()
        parser._parse_with_agent = AsyncMock(return_value={"success": True, "message": "Agent handled it"})

        executor = AsyncMock()

        result = await parser.parse("do something complicated with my work stuff", executor=executor)

        executor.execute.assert_not_called()
        parser._parse_with_agent.assert_awaited_once()
        assert result == {"success": True, "message": "Agent handled it"}

    @pytest.mark.asyncio
    async def test_parse_uses_alternative_transcript_for_deterministic_match(self):
        parser = self._make_configured_parser()
        parser._parse_with_agent = AsyncMock()

        executor = AsyncMock()
        executor.execute.return_value = {"success": True, "message": "Searched web"}

        result = await parser.parse(
            "shut novel",
            executor=executor,
            alternatives=["shut novel", "search novel"],
        )

        executor.execute.assert_awaited_once_with({
            "action": "browser_search",
            "params": {"query": "novel", "engine": "google"},
        })
        parser._parse_with_agent.assert_not_called()
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_parse_executes_deterministic_sequence(self):
        parser = self._make_configured_parser()
        parser._parse_with_agent = AsyncMock()

        executor = AsyncMock()
        executor.execute.side_effect = [
            {"success": True, "message": "Volume set to 100%"},
            {"success": True, "message": "Opened YouTube search for 'cbr 1000 rr fire blade' in the default browser"},
        ]

        result = await parser.parse(
            "set volume to 100% and then open YouTube and search for cbr 1000 rr fire blade",
            executor=executor,
        )

        assert executor.execute.await_count == 2
        assert executor.execute.await_args_list[0].args[0] == {
            "action": "set_volume",
            "params": {"level": 100},
        }
        assert executor.execute.await_args_list[1].args[0] == {
            "action": "yt_search",
            "params": {"query": "cbr 1000 rr fire blade"},
        }
        parser._parse_with_agent.assert_not_called()
        assert result == {
            "success": True,
            "message": "Volume set to 100% Then Opened YouTube search for 'cbr 1000 rr fire blade' in the default browser",
        }

    @pytest.mark.asyncio
    async def test_parse_stream_executes_deterministic_sequence(self):
        parser = self._make_configured_parser()
        parser._parse_with_agent_stream = AsyncMock()

        executor = AsyncMock()
        executor.execute.side_effect = [
            {"success": True, "message": "Volume set to 100%"},
            {"success": True, "message": "Opened YouTube search for 'cbr 1000 rr fire blade' in the default browser"},
        ]

        chunks = [
            chunk
            async for chunk in parser.parse_stream(
                "set volume to 100% and then open YouTube and search for cbr 1000 rr fire blade",
                executor=executor,
            )
        ]

        assert executor.execute.await_count == 2
        parser._parse_with_agent_stream.assert_not_called()
        assert chunks == [{
            "type": "final",
            "result": {
                "success": True,
                "message": "Volume set to 100% Then Opened YouTube search for 'cbr 1000 rr fire blade' in the default browser",
            },
        }]
