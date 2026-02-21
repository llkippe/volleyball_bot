FROM python:3.12-slim

# Notwendige Abhängigkeiten für Chrome und ChromeDriver installieren
RUN apt-get update && \
    apt-get install -y \
    wget \
    gnupg \
    unzip \
    lsb-release && \
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor > /etc/apt/trusted.gpg.d/google-chrome.gpg && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# ChromeDriver herunterladen und entpacken (Version 145.0.7632.76)
RUN wget -O /tmp/chromedriver.zip 	https://storage.googleapis.com/chrome-for-testing-public/145.0.7632.76/linux64/chrome-linux64.zip && \
    unzip /tmp/chromedriver.zip -d /usr/bin/ && \
    rm /tmp/chromedriver.zip



WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

#COPY test.py .
#CMD ["python", "test.py"]

COPY bot.py .
CMD ["python", "bot.py"]