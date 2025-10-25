import time
import uvicorn
import logging
import argparse
import requests

from datetime import timedelta
from fastapi import FastAPI, HTTPException, status
from bedrock_agentcore.services.identity import IdentityClient, UserTokenIdentifier


OAUTH2_CALLBACK_SERVER_PORT = 9090
PING_ENDPOINT = "/ping"
OAUTH2_CALLBACK_ENDPOINT = "/oauth2/callback"
USER_IDENTIFIER_ENDPOINT = "/userIdentifier/token"

logger = logging.getLogger(__name__)


class OAuth2CallbackServer:
    def __init__(self, region: str):
        self.identity_client = IdentityClient(region=region)
        self.user_token_identifier = None
        self.app = FastAPI()
        self._setup_routes()

    def _setup_routes(self):
        @self.app.post(USER_IDENTIFIER_ENDPOINT)
        async def _store_user_token(user_token_identifier_value: UserTokenIdentifier):
            self.user_token_identifier = user_token_identifier_value

        @self.app.get(PING_ENDPOINT)
        async def _handle_ping():
            return {"status": "success"}

        @self.app.get(OAUTH2_CALLBACK_ENDPOINT)
        async def _handle_oauth2_callback(session_id: str):
            if not session_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing session_id query parameter",
                )

            if not self.user_token_identifier:
                logger.error("No configured user token identifier")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Internal Server Error",
                )

            self.identity_client.complete_resource_token_auth(
                session_uri=session_id, user_identifier=self.user_token_identifier
            )

            return {"message": "completed OAuth2 3LO flow successfully"}

    def get_app(self) -> FastAPI:
        return self.app


def get_oauth2_callback_url() -> str:
    return f"http://localhost:{OAUTH2_CALLBACK_SERVER_PORT}{OAUTH2_CALLBACK_ENDPOINT}"


def store_token_in_oauth2_callback_server(user_token_value: str):
    if user_token_value:
        requests.post(
            f"http://localhost:{OAUTH2_CALLBACK_SERVER_PORT}{USER_IDENTIFIER_ENDPOINT}",
            json={"user_token": user_token_value},
            timeout=2,
        )
    else:
        logger.error("Ignoring: invalid user_token provided...")


def wait_for_oauth2_server_to_be_ready(
    duration: timedelta = timedelta(seconds=40),
) -> bool:
    logger.info("Waiting for OAuth2 callback server to be ready...")
    timeout_in_seconds = duration.seconds

    start_time = time.time()
    while time.time() - start_time < timeout_in_seconds:
        try:
            response = requests.get(
                f"http://localhost:{OAUTH2_CALLBACK_SERVER_PORT}{PING_ENDPOINT}",
                timeout=2,
            )
            if response.status_code == status.HTTP_200_OK:
                logger.info("OAuth2 callback server is ready!")
                return True
        except requests.exceptions.RequestException:
            pass

        time.sleep(2)
        elapsed = int(time.time() - start_time)
        if elapsed % 10 == 0 and elapsed > 0:
            logger.info(f"Still waiting... ({elapsed}/{timeout_in_seconds}s)")

    logger.error(
        f"Timeout: OAuth2 callback server not ready after {timeout_in_seconds} seconds"
    )
    return False


def main():
    parser = argparse.ArgumentParser(description="OAuth2 Callback Server")
    parser.add_argument(
        "-r", "--region", type=str, required=True, help="AWS Region (e.g. us-east-1)"
    )

    args = parser.parse_args()
    oauth2_callback_server = OAuth2CallbackServer(region=args.region)

    uvicorn.run(
        oauth2_callback_server.get_app(),
        host="127.0.0.1",
        port=OAUTH2_CALLBACK_SERVER_PORT,
    )


if __name__ == "__main__":
    main()
