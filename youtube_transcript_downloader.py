import asyncio
import itertools
import os
import argparse
from typing import List, Optional, Dict
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from googleapiclient.discovery import build
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()


def background(f):
    """
    Decorator that turns a synchronous function into an asynchronous function by running it in an
    executor using the default event loop.

    Args:
        f (Callable): The function to be turned into an asynchronous function.

    Returns:
        Callable: The wrapped function that can be called asynchronously.
    """
    def wrapped(*args, **kwargs):
        """
        Wrapper function that calls the original function 'f' in an executor using the default event loop.

        Args:
            *args: Positional arguments to pass to the original function 'f'.
            **kwargs: Keyword arguments to pass to the original function 'f'.

        Returns:
            Any: The result of the original function 'f'.
        """
        return asyncio.get_event_loop().run_in_executor(None, f, *args, **kwargs)

    return wrapped


def get_video_info(api_key: str, channel_id: str, max_results: int = 500000) -> List[dict]:
    """
    Retrieves video information (URL, ID, and title) from a YouTube channel using the YouTube Data API.

    Args:
        api_key (str): Your YouTube Data API key.
        channel_id (str): The YouTube channel ID.
        max_results (int, optional): Maximum number of results to retrieve. Defaults to 50.

    Returns:
        list: A list of dictionaries containing video URL, ID, and title from the channel.
    """
    youtube = build('youtube', 'v3', developerKey=api_key)

    # Get the "Uploads" playlist ID
    channel_request = youtube.channels().list(
        part="contentDetails",
        id=channel_id,
        fields="items/contentDetails/relatedPlaylists/uploads"
    )
    channel_response = channel_request.execute()
    uploads_playlist_id = channel_response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Fetch videos from the "Uploads" playlist
    video_info = []
    next_page_token = None

    while True:
        playlist_request = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_playlist_id,
            maxResults=max_results,
            pageToken=next_page_token,
            fields="nextPageToken,items(snippet(publishedAt,resourceId(videoId),title))"
        )
        playlist_response = playlist_request.execute()
        items = playlist_response.get('items', [])

        for item in items:
            video_id = item["snippet"]["resourceId"]["videoId"]
            video_info.append({
                'url': f'https://www.youtube.com/watch?v={video_id}',
                'id': video_id,
                'title': item["snippet"]["title"],
                'publishedAt': item["snippet"]["publishedAt"]
            })

        next_page_token = playlist_response.get("nextPageToken")

        if next_page_token is None or len(video_info) >= max_results:
            break
    return video_info


@background
def parse_video(video_info: Dict[str, str], dir_path: str) -> None:
    """
    Fetch and save the transcript of a YouTube video as a .txt file.

    Args:
        video_info (Dict[str, str]): A dictionary containing video information such as 'id', 'title', and 'publishedAt'.
        dir_path (str): The directory path where the transcript file will be saved.

    Returns:
        None
    """

    # Get video ID
    video_id = video_info['id']

    try:
        # Format video title and published date for file naming
        video_title = video_info['title'].replace(' ', '_').replace('/', '_')
        strlen = len("yyyy-mm-dd")
        published_at = video_info['publishedAt'].replace(':', '-').replace('.', '-')[:strlen]
        video_title = f"{published_at}_{video_title}"

        # Create the file path for the transcript
        file_path = os.path.join(dir_path, f'{video_title}.txt')

        # If the file already exists, skip it
        if os.path.exists(file_path):
            return

        # Log the attempt to fetch the transcript
        print(f"TRYING VIDEO: [{file_path}]")

        try:
            # Get the transcript
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
        except TranscriptsDisabled:
            print(f"No transcripts available for {video_info['url']} with title {video_title}")
            return
        except NoTranscriptFound:
            try:
                transcript = YouTubeTranscriptApi.get_transcript(video_id)
            except Exception as e:
                print(f"Error fetching translated transcript for {video_info['url']} with title {video_title}: {e}")
                return
        except Exception as e:
            print(f"Unknown error [{e}] for {video_title}")
            return

        # Write the transcript to a .txt file
        with open(file_path, 'w') as f:
            for line in transcript:
                f.write(f"{line['text']} ")

        print(f'Successfully saved transcript for {video_info["url"]} as {file_path}')

    except Exception as e:
        print(f'Error fetching transcript for {video_info["url"]} with title {video_title}: {e}')


def get_channel_id(api_key: str, channel_name: str) -> Optional[str]:
    """
    Get the channel ID of a YouTube channel by its name.

    Args:
        api_key (str): Your YouTube Data API key.
        channel_name (str): The name of the YouTube channel.

    Returns:
        Optional[str]: The channel ID if found, otherwise None.
    """

    # Initialize the YouTube API client
    youtube = build('youtube', 'v3', developerKey=api_key)

    # Create a search request to find the channel by name
    request = youtube.search().list(
        part='snippet',
        type='channel',
        q=channel_name,
        maxResults=1,
        fields='items(id(channelId))'
    )

    # Execute the request and get the response
    response = request.execute()

    # Get the list of items (channels) from the response
    items = response.get('items', [])

    # If there is at least one item, return the channel ID, otherwise return None
    if items:
        return items[0]['id']['channelId']
    else:
        return None


def run(api_key: str, yt_channels: List[str]):
    """
    Run function that takes a YouTube Data API key and a list of YouTube channel names, fetches video transcripts,
    and saves them as .txt files in a data directory.

    Args:
        api_key (str): Your YouTube Data API key.
        yt_channels (List[str]): A list of YouTube channel names.
    """

    # Create a dictionary with channel IDs as keys and channel names as values
    yt_id_name = {get_channel_id(api_key=api_key, channel_name=name): name for name in yt_channels}

    # Iterate through the dictionary of channel IDs and channel names
    for channel_id, channel_name in yt_id_name.items():

        # Get video information from the channel
        video_info_list = get_video_info(api_key, channel_id)

        # Create a 'data' directory if it does not exist
        dir_path = 'data'
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        # Create a subdirectory for the current channel if it does not exist
        dir_path += f'/{channel_name}'
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        # Iterate through video information, fetch transcripts, and save them as .txt files
        loop = asyncio.get_event_loop()
        args = [(video_info, dir_path) for video_info in video_info_list]

        tasks = itertools.starmap(parse_video, args)
        loop.run_until_complete(asyncio.gather(*tasks))


if __name__ == '__main__':
    # Set up command line argument parser
    parser = argparse.ArgumentParser(description='Fetch YouTube video transcripts.')
    parser.add_argument('--api_key', type=str, help='YouTube Data API key')
    parser.add_argument('--channels', nargs='+', type=str, help='YouTube channel names or IDs')

    # Parse command line arguments
    args = parser.parse_args()

    # Get the API key from command line arguments or environment variable
    api_key = args.api_key or os.environ.get('YOUTUBE_API_KEY')

    if not api_key:
        raise ValueError("No API key provided. Please provide an API key via command line argument or .env file.")

    # Get the list of channels from command line arguments or environment variable
    yt_channels = args.channels or os.environ.get('YOUTUBE_CHANNELS')
    if yt_channels:
        yt_channels = [channel.strip() for channel in yt_channels.split(',')]
    else:
        raise ValueError("No channels provided. Please provide channel names or IDs via command line argument or .env file.")

    run(api_key, yt_channels)

