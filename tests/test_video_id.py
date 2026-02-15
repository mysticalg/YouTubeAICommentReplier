from YouTubeCommentResponder import build_parser, extract_video_id


def test_extract_video_id_watch_url():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_short_url():
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_extract_video_id_invalid():
    assert extract_video_id("https://example.com") is None


def test_auth_mode_argument_default_auto():
    parser = build_parser()
    args = parser.parse_args(["https://youtu.be/dQw4w9WgXcQ"])
    assert args.auth_mode == "auto"
