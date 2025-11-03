"""YouTube Data API v3 client with OAuth2 authentication."""
from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# OAuth2 scopes for YouTube readonly access
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

# Token storage location
TOKEN_FILE = "config/youtube_token.pickle"
CLIENT_SECRET_FILE = "config/youtube_client_secret.json"


class YouTubeAPIClient:
    """Client for YouTube Data API v3 with OAuth2."""

    def __init__(self, client_secret_path: Optional[str] = None, token_path: Optional[str] = None):
        """Initialize YouTube API client.
        
        Args:
            client_secret_path: Path to client_secret.json (OAuth credentials)
            token_path: Path to store/load authentication token
        """
        self.client_secret_path = client_secret_path or CLIENT_SECRET_FILE
        self.token_path = token_path or TOKEN_FILE
        self._service = None
        self._credentials = None

    def authenticate(self) -> None:
        """Authenticate with YouTube API using OAuth2.
        
        This will:
        1. Try to load existing credentials from token file
        2. Refresh credentials if expired
        3. Launch OAuth flow in browser if needed
        """
        creds = None
        
        # Load existing token if available
        if os.path.exists(self.token_path):
            with open(self.token_path, "rb") as token:
                creds = pickle.load(token)
        
        # If no valid credentials, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("[YouTube API] Refreshing expired credentials...")
                creds.refresh(Request())
            else:
                # No valid credentials - run OAuth flow
                if not os.path.exists(self.client_secret_path):
                    raise FileNotFoundError(
                        f"Client secret file not found: {self.client_secret_path}\n"
                        "Please download OAuth credentials from Google Cloud Console."
                    )
                
                print("[YouTube API] Starting OAuth authentication flow...")
                print("A browser window will open for you to authorize access.")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secret_path, SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save credentials for next time
            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            with open(self.token_path, "wb") as token:
                pickle.dump(creds, token)
            print(f"[YouTube API] Credentials saved to {self.token_path}")
        
        self._credentials = creds
        self._service = build("youtube", "v3", credentials=creds)
        print("[YouTube API] Authentication successful!")

    @property
    def service(self):
        """Get YouTube API service (authenticates if needed)."""
        if self._service is None:
            self.authenticate()
        return self._service

    def get_my_subscriptions(self, max_results: int = 50) -> List[dict]:
        """Get list of channels the authenticated user is subscribed to.
        
        Args:
            max_results: Maximum number of subscriptions to fetch (max 50 per page)
        
        Returns:
            List of subscription items with channel info
        """
        subscriptions = []
        next_page_token = None
        
        try:
            while True:
                request = self.service.subscriptions().list(
                    part="snippet",
                    mine=True,
                    maxResults=min(max_results, 50),
                    pageToken=next_page_token,
                )
                response = request.execute()
                
                subscriptions.extend(response.get("items", []))
                
                # Check if we've fetched enough or if there are more pages
                next_page_token = response.get("nextPageToken")
                if not next_page_token or len(subscriptions) >= max_results:
                    break
            
            return subscriptions[:max_results]
        
        except HttpError as e:
            print(f"[YouTube API] Error fetching subscriptions: {e}")
            raise

    def get_subscription_channel_ids(self, max_results: int = 50) -> List[str]:
        """Get list of channel IDs for all subscriptions.
        
        Args:
            max_results: Maximum number of channels to fetch
        
        Returns:
            List of channel IDs (e.g., ['UCxxxxx', 'UCyyyyy', ...])
        """
        subscriptions = self.get_my_subscriptions(max_results=max_results)
        channel_ids = []
        
        for sub in subscriptions:
            snippet = sub.get("snippet", {})
            resource_id = snippet.get("resourceId", {})
            channel_id = resource_id.get("channelId")
            if channel_id:
                channel_ids.append(channel_id)
        
        return channel_ids

    def get_subscription_details(self, max_results: int = 50) -> List[dict]:
        """Get detailed info about subscriptions.
        
        Returns:
            List of dicts with channel_id, title, description
        """
        subscriptions = self.get_my_subscriptions(max_results=max_results)
        details = []
        
        for sub in subscriptions:
            snippet = sub.get("snippet", {})
            resource_id = snippet.get("resourceId", {})
            
            details.append({
                "channel_id": resource_id.get("channelId"),
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "published_at": snippet.get("publishedAt"),
            })
        
        return details

    def get_activities(self, max_results: int = 25) -> List[dict]:
        """Get recent activities (videos from subscriptions feed).
        
        This returns videos from channels you're subscribed to.
        
        Args:
            max_results: Maximum number of activities to fetch
        
        Returns:
            List of activity items
        """
        try:
            request = self.service.activities().list(
                part="snippet,contentDetails",
                home=True,
                maxResults=min(max_results, 50),
            )
            response = request.execute()
            return response.get("items", [])
        
        except HttpError as e:
            print(f"[YouTube API] Error fetching activities: {e}")
            raise


def test_client():
    """Test YouTube API client."""
    client = YouTubeAPIClient()
    
    print("Authenticating...")
    client.authenticate()
    
    print("\nFetching subscriptions...")
    channel_ids = client.get_subscription_channel_ids(max_results=10)
    print(f"Found {len(channel_ids)} subscriptions:")
    for channel_id in channel_ids[:5]:
        print(f"  - {channel_id}")
    
    print("\nFetching subscription details...")
    details = client.get_subscription_details(max_results=5)
    for detail in details:
        print(f"  - {detail['title']} ({detail['channel_id']})")


if __name__ == "__main__":
    test_client()

