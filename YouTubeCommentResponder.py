import os
import re
import pickle
import openai
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Set the scope and client secrets file for YouTube API authentication
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRETS_FILE = "client_secrets.json"  # Make sure this file is in the same directory

def get_authenticated_service():
    """
    Authenticate and return an authorized YouTube API client.
    Credentials are stored in 'token.pickle' for later use.
    """
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    # If there are no valid credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_console()
        # Save the credentials for the next run
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
    return build("youtube", "v3", credentials=creds)

def extract_video_id(url):
    """
    Extract the YouTube video ID from a URL.
    """
    pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    else:
        return None

def get_video_comments(youtube, video_id, max_comments=20):
    """
    Retrieve up to max_comments top-level comments from the given video.
    """
    comments = []
    try:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=100,
            textFormat="plainText"
        )
        response = request.execute()
        while response and len(comments) < max_comments:
            for item in response.get("items", []):
                comment = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
                comments.append(comment)
                if len(comments) >= max_comments:
                    break
            if "nextPageToken" in response and len(comments) < max_comments:
                response = youtube.commentThreads().list(
                    part="snippet",
                    videoId=video_id,
                    maxResults=100,
                    pageToken=response["nextPageToken"],
                    textFormat="plainText"
                ).execute()
            else:
                break
    except HttpError as e:
        print(f"An error occurred while fetching comments: {e}")
    return comments

def generate_openai_response(prompt):
    """
    Send the prompt to the OpenAI API and return the generated response.
    """
    try:
        response = openai.Completion.create(
            engine="text-davinci-003",  # You can use another engine if you prefer
            prompt=prompt,
            max_tokens=150,  # Adjust as needed
            temperature=0.7
        )
        return response.choices[0].text.strip()
    except Exception as e:
        print(f"An error occurred with OpenAI API: {e}")
        return None

def post_comment(youtube, video_id, text):
    """
    Post a top-level comment on the specified YouTube video.
    """
    body = {
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {
                "snippet": {
                    "textOriginal": text
                }
            }
        }
    }
    try:
        response = youtube.commentThreads().insert(
            part="snippet",
            body=body
        ).execute()
        print("Comment posted successfully!")
        return response
    except HttpError as e:
        print(f"An error occurred while posting the comment: {e}")
        return None

def main():
    # Set your OpenAI API key (ensure you have set this environment variable)
    openai.api_key = os.getenv("OPENAI_API_KEY")
    if not openai.api_key:
        print("Please set your OpenAI API key in the OPENAI_API_KEY environment variable.")
        return

    # Get YouTube video URL from the user
    video_url = input("Enter YouTube video URL: ").strip()
    video_id = extract_video_id(video_url)
    if not video_id:
        print("Could not extract video ID from the provided URL.")
        return

    # Authenticate and create YouTube API client
    youtube = get_authenticated_service()

    # Retrieve comments from the video
    print("Fetching video comments...")
    comments = get_video_comments(youtube, video_id, max_comments=20)
    if not comments:
        print("No comments found or unable to fetch comments.")
        return

    # Combine comments into a single text block (note: adjust if too many tokens for OpenAI API)
    combined_comments = "\n".join(comments)
    prompt = (
        f"The following are comments from a YouTube video:\n{combined_comments}\n\n"
        "Based on these comments, please generate a thoughtful and helpful response."
    )

    # Generate a response using OpenAI
    print("Generating response using OpenAI API...")
    generated_response = generate_openai_response(prompt)
    if not generated_response:
        print("Failed to generate a response from OpenAI.")
        return

    print("\nGenerated response:")
    print(generated_response)

    # Post the generated response back to YouTube as a comment
    print("\nPosting the generated response as a comment on the video...")
    post_comment(youtube, video_id, generated_response)

if __name__ == "__main__":
    main()
