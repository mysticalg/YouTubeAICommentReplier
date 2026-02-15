from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
VIDEO_ID_REGEX = r"(?:v=|/)([0-9A-Za-z_-]{11})(?:[?&].*)?$"


@dataclass
class AppConfig:
    openai_api_key: str
    openai_model: str
    client_secrets_file: Path
    token_file: Path
    max_comments: int
    dry_run: bool
    auth_mode: str


def extract_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from common URL formats."""
    match = re.search(VIDEO_ID_REGEX, url.strip())
    return match.group(1) if match else None


def get_authenticated_service(client_secrets_file: Path, token_file: Path, auth_mode: str = "auto"):
    """Authenticate with OAuth and return YouTube API client.

    auth_mode:
      - auto: try local webserver flow first, fallback to console flow
      - local: force local webserver callback flow
      - console: force console/device-code style flow (best for SSH/Android/Termux)
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)

            if auth_mode == "console":
                creds = flow.run_console()
            elif auth_mode == "local":
                creds = flow.run_local_server(port=0)
            else:
                try:
                    creds = flow.run_local_server(port=0)
                except Exception:
                    creds = flow.run_console()

        token_file.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def get_video_comments(youtube, video_id: str, max_comments: int) -> List[str]:
    """Retrieve top-level comments from a video."""
    comments: List[str] = []
    response = (
        youtube.commentThreads()
        .list(part="snippet", videoId=video_id, maxResults=100, textFormat="plainText")
        .execute()
    )

    while response and len(comments) < max_comments:
        for item in response.get("items", []):
            comment = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            comments.append(comment)
            if len(comments) >= max_comments:
                break

        next_page_token = response.get("nextPageToken")
        if next_page_token and len(comments) < max_comments:
            response = (
                youtube.commentThreads()
                .list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=100,
                    pageToken=next_page_token,
                    textFormat="plainText",
                )
                .execute()
            )
        else:
            break

    return comments


def generate_openai_response(api_key: str, model: str, comments: List[str]) -> str:
    """Generate an AI reply based on comments from the video."""
    from openai import OpenAI

    joined_comments = "\n".join(f"- {comment}" for comment in comments)
    prompt = (
        "You are helping a YouTube creator reply to the audience. "
        "Write one concise, warm, and community-friendly public comment reply.\n\n"
        f"Audience comments:\n{joined_comments}\n\n"
        "Constraints: keep it under 120 words, avoid promises, avoid spammy tone, and include gratitude."
    )

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=prompt,
        max_output_tokens=220,
        temperature=0.7,
    )
    return response.output_text.strip()


def post_comment(youtube, video_id: str, text: str):
    """Post a top-level comment on the specified YouTube video."""
    body = {
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {"snippet": {"textOriginal": text}},
        }
    }
    return youtube.commentThreads().insert(part="snippet", body=body).execute()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and post an AI reply to YouTube comments.")
    parser.add_argument("video_url", help="YouTube video URL")
    parser.add_argument("--max-comments", type=int, default=20, help="Number of comments to analyze")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), help="OpenAI model")
    parser.add_argument("--client-secrets", default="client_secrets.json", help="Path to Google OAuth client secrets JSON")
    parser.add_argument("--token-file", default="token.json", help="Path to store OAuth token")
    parser.add_argument(
        "--auth-mode",
        choices=["auto", "local", "console"],
        default="auto",
        help="OAuth flow mode: auto/local/console (use console for Android/Termux or headless shells)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not post; only print generated comment")
    return parser


def load_config(args: argparse.Namespace) -> AppConfig:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set. Add it to your environment before running.")

    client_secrets_file = Path(args.client_secrets)
    if not client_secrets_file.exists():
        raise FileNotFoundError(
            f"Google OAuth client secrets file not found: {client_secrets_file}. "
            "Download it from Google Cloud Console."
        )

    if args.max_comments < 1 or args.max_comments > 100:
        raise ValueError("--max-comments must be between 1 and 100.")

    return AppConfig(
        openai_api_key=api_key,
        openai_model=args.model,
        client_secrets_file=client_secrets_file,
        token_file=Path(args.token_file),
        max_comments=args.max_comments,
        dry_run=args.dry_run,
        auth_mode=args.auth_mode,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    video_id = extract_video_id(args.video_url)
    if not video_id:
        print("❌ Could not extract a valid YouTube video ID from the URL.")
        return 1

    try:
        config = load_config(args)
        youtube = get_authenticated_service(
            config.client_secrets_file,
            config.token_file,
            auth_mode=config.auth_mode,
        )

        print("Fetching comments...")
        comments = get_video_comments(youtube, video_id, config.max_comments)
        if not comments:
            print("❌ No comments found or unable to fetch comments.")
            return 1

        print(f"Generating AI response from {len(comments)} comments...")
        generated_response = generate_openai_response(
            api_key=config.openai_api_key,
            model=config.openai_model,
            comments=comments,
        )

        print("\n--- Generated response ---")
        print(generated_response)

        if config.dry_run:
            print("\nDry run enabled. Skipping YouTube post.")
            return 0

        post_comment(youtube, video_id, generated_response)
        print("\n✅ Comment posted successfully.")
        return 0

    except (ValueError, FileNotFoundError) as err:
        print(f"❌ {err}")
        return 1
    except Exception as err:
        if err.__class__.__name__ == "HttpError":
            print(f"❌ YouTube API error: {err}")
            return 1
        print(f"❌ Unexpected error: {err}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
