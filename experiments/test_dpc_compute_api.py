"""Live POST /v1/compute contract probe; run after docker compose up api."""
import httpx

URL = "http://localhost:8000/v1/compute"
HEADERS = {"Authorization": "Bearer dev-token"}


def main():
    with httpx.Client(timeout=30) as client:
        request = {"a": 0, "b": 90, "n": 10000, "workers": 2,
                   "method": "simpson", "order": 4}
        unauthorized = client.post(URL, json=request)
        assert unauthorized.status_code == 401, unauthorized.text
        result = client.post(URL, json=request, headers=HEADERS)
        assert result.status_code == 200, result.text
        assert result.json()["error"] < 0.02, result.text
        bad = client.post(URL, json={**request, "a": 90, "b": 0}, headers=HEADERS)
        assert bad.status_code == 400, bad.text
        print(result.json())


if __name__ == "__main__":
    main()
