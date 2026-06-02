import json
import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from google.auth import default
from google.cloud import storage
from jinja2 import Template
from pyppeteer import launch

# Load environment variables
load_dotenv()

BASE_ROUTE = "/v1/image-attributor"

app = FastAPI(root_path=BASE_ROUTE, debug=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure GCS Client
service_account_json_str = os.getenv('SERVICE_ACCOUNT')
if service_account_json_str:
    # Use the service account credentials from the environment variable
    service_account_info = json.loads(service_account_json_str)
    GCS_CLIENT = storage.Client.from_service_account_info(service_account_info)
else:
    # Use the default credentials for local development
    credentials, project = default()
    GCS_CLIENT = storage.Client(credentials=credentials, project=project)

# GCS bucket name
GCS_BUCKET_NAME = "img-cdn-bucket"

# Base directory to work with absolute paths
base_dir = os.path.dirname(os.path.abspath(__file__))


# logger.debug(f"Base directory: {base_dir}")

@app.get(f"/")
async def health():
    return {"message": "API is healthy!"}


@app.post("/generate-image")
async def generate_image(request: Request):
    """Endpoint to generate an image."""
    data = await request.json()
    title = data.get("title")
    image_url = data.get("image_url")
    publisher = data.get("publisher")
    summary_id = data.get("summary_id")

    # Validate required parameters
    if not all([title, image_url, publisher, summary_id]):
        raise HTTPException(status_code=400, detail="Missing required parameters")

    try:
        # Step 1: Render the HTML template
        html_template_path = os.path.join(base_dir, 'template.html')
        # logger.debug(f"HTML template path: {html_template_path}")
        if not os.path.exists(html_template_path):
            raise HTTPException(status_code=500, detail="HTML template file not found.")

        with open(html_template_path, 'r', encoding='utf-8') as file:
            html_template = file.read()

        template = Template(html_template)
        rendered_html = template.render(title=title, publisher_name=publisher, image_url=image_url)

        # Step 2: Save the HTML to a temporary file
        temp_html_path = os.path.join(base_dir, f'{summary_id}.html')
        with open(temp_html_path, "w", encoding="utf-8") as html_file:
            html_file.write(rendered_html)

        # Step 3: Generate a JPEG using Pyppeteer
        temp_image_path = os.path.join(base_dir, f'{summary_id}.jpeg')
        await html_to_jpeg(temp_html_path, temp_image_path)

        # Step 4: Upload the image to GCS
        upload_to_gcs(temp_image_path, summary_id)

        # Step 5: Delete the temporary files
        os.remove(temp_html_path)
        os.remove(temp_image_path)

        return JSONResponse({"message": "Image generated and uploaded successfully", "summary_id": summary_id})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def html_to_jpeg(html_path: str, output_path: str):
    """Convert an HTML file to a JPEG image using Pyppeteer."""
    # chromium_path = "C:\\Users\\Ankit10.Joshi\\PycharmProjects\\Resource\\chrome-win\\chrome.exe"  # Ensure this path is correct
    browser = await launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox"])
    page = await browser.newPage()
    # Set the viewport size to match the desired dimensions
    await page.setViewport({"width": 1920, "height": 1080})
    # Use correct file path format for Pyppeteer
    await page.goto(f"file:///{html_path.replace('\\', '/')}")
    await page.screenshot({"path": output_path, "type": "jpeg"})
    await browser.close()


def upload_to_gcs(file_path: str, summary_id: str):
    """Upload a file to Google Cloud Storage."""
    bucket = GCS_CLIENT.get_bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(f"jio_bharat/{summary_id}.jpeg")
    blob.upload_from_filename(file_path)
    print(f"Uploaded {file_path} to GCS bucket {GCS_BUCKET_NAME} as jio_bharat/{summary_id}.jpeg")

# uvicorn src.app:app --reload