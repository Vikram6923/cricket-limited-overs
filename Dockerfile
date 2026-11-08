# The browser UI as a hosted site (python web_ui.py --public). See README "Hosting it for friends".
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only what the site needs: the engine, the page and the data (not the build scripts or raw downloads).
COPY engine engine
COPY webui webui
COPY data data
COPY web_ui.py .

# Run as an ordinary user; results/ (visitors' runs, teams and careers) is the only folder it writes to.
RUN useradd --create-home --uid 10001 cricket && mkdir -p results && chown cricket:cricket results
USER cricket
VOLUME /app/results

EXPOSE 8080
CMD ["python", "web_ui.py", "--public"]
