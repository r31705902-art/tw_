import asyncio
from playwright.async_api import async_playwright
import json

async def capture():
    async with async_playwright() as p:
        # Launch existing chromium
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        network_data = []

        async def handle_request(request):
            post_data = None
            try:
                if request.post_data_buffer:
                    try:
                        post_data = request.post_data_buffer.decode('utf-8')
                    except UnicodeDecodeError:
                        post_data = f"<binary data: {len(request.post_data_buffer)} bytes>"
            except Exception as e:
                 post_data = f"<error reading post data: {e}>"

            network_data.append({
                'type': 'request',
                'method': request.method,
                'url': request.url,
                'headers': request.headers,
                'postData': post_data
            })

        async def handle_response(response):
            network_data.append({
                'type': 'response',
                'status': response.status,
                'url': response.url,
                'headers': response.headers
            })

        page.on('request', handle_request)
        page.on('response', handle_response)

        print("Navigating to Twitch...")
        try:
            await page.goto('https://www.twitch.tv/?lang=en', wait_until='networkidle')
            
            signup_button = page.locator('button[data-a-target="login-button"]')
            if await signup_button.is_visible():
                 await signup_button.click()
                 print("Clicked login/signup button")
                 await asyncio.sleep(2)

                 signup_tab = page.locator('button[data-a-target="signup-tab"]')
                 if await signup_tab.is_visible():
                     await signup_tab.click()
                     print("Clicked signup tab")
                     await asyncio.sleep(2)

            print("Waiting 20 seconds for traffic capture...")
            await asyncio.sleep(20)

            with open('twitch_traffic.json', 'w') as f:
                json.dump(network_data, f, indent=2)
            print("Traffic saved to twitch_traffic.json")

        except Exception as e:
            print(f"An error occurred: {e}")

        finally:
            await browser.close()

if __name__ == '__main__':
    asyncio.run(capture())
