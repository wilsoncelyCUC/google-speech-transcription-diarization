# 🎙️ Google Speech Transcription with Diarization

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python Version](https://img.shields.io/badge/python-3.8%2B-brightgreen)
![Status](https://img.shields.io/badge/status-active-success.svg)

> A powerful open-source audio transcription tool with speaker diarization capabilities, built on Google Cloud Speech-to-Text API

This tool automatically transcribes audio files into text while identifying different speakers in conversations. It handles MP3 conversion, provides visual feedback throughout the process, and produces clean, organized transcripts.

## ✨ Features

- 🎯 **Automatic Speaker Identification** - Distinguishes between different speakers in the conversation
- 🔄 **Audio Format Conversion** - Automatically converts MP3 files to FLAC for optimal processing
- 📊 **Live Progress Visualization** - See real-time progress for conversion, uploads, and processing
- 🌐 **Multi-language Support** - Transcribe audio in numerous languages
- 🔍 **Enhanced Recognition** - Optional high-accuracy model for important transcriptions
- 💾 **Organized Output** - Clean, readable transcripts saved as text files

## 🚀 Getting Started

### Prerequisites

- Python 3.8 or higher
- Google Cloud Platform account with Speech-to-Text API enabled
- Google Cloud Storage bucket
- FFmpeg installed (for MP3 conversion)

### Installation

1. Clone this repository
```bash
git clone https://github.com/wilsoncelyCUC/google-speech-transcription-diarization.git
cd google-speech-transcription-diarization
```

Or with SSH:
```bash
git clone git@github.com:wilsoncelyCUC/google-speech-transcription-diarization.git
cd google-speech-transcription-diarization
```

2. Create and activate a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Set up your environment variables by creating a `.env` file:
```
GOOGLE_APPLICATION_CREDENTIALS="/path/to/your-service-account-key.json"
GCS_BUCKET_NAME="your-gcs-bucket-name"
```

### Basic Usage

```bash
python transcribe_final.py your-audio-file.mp3
```

That's it! Your transcription will be saved to the `output` folder.

## 🎛️ Advanced Options

```
python transcribe_final.py your-audio-file.mp3 [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-l`, `--language` | Language code (e.g., en-US, es-ES, fr-FR). Default is en-US. |
| `--min_speakers` | Minimum number of speakers expected. Default is 1. |
| `--max_speakers` | Maximum number of speakers expected. Default is 5. |
| `--sample_rate` | Sample rate in Hz (required for non-MP3 files). |
| `--encoding` | Audio encoding type (required for non-MP3 files). |
| `-o`, `--output` | Custom output file path. |
| `--enhanced` | Use enhanced model for better accuracy. |

### Example Commands

**Transcribe an MP3 file in Spanish with 2-3 speakers:**
```bash
python transcribe_final.py interview.mp3 --language es-ES --min_speakers 2 --max_speakers 3
```

**Use enhanced model for better accuracy:**
```bash
python transcribe_final.py conference.mp3 --enhanced
```

**Specify custom output location:**
```bash
python transcribe_final.py meeting.mp3 -o "transcripts/meeting_transcript.txt"
```

## 📝 Output Format

```
Speaker 1: This is the first person speaking. They might say several sentences.

Speaker 2: This is the second person responding to the first speaker.

Speaker 1: The conversation continues with speakers identified.
```

## 🛠️ Troubleshooting

Common issues:

1. **Error: GOOGLE_APPLICATION_CREDENTIALS environment variable not set**
   - Make sure your `.env` file exists in the same directory as the script
   - Check that the path to your service account key file is correct

2. **Error: FFmpeg command not found**
   - Ensure FFmpeg is properly installed
   - Verify FFmpeg is in your system PATH
   - Try running `ffmpeg -version` to confirm it's accessible

3. **Error: The API returned no transcription results**
   - Check if your audio file has clear speech
   - Try using the `--enhanced` flag for better recognition
   - If the audio is in a language other than English, specify the correct language code

## 🤝 Contributing

Contributions are welcome! Feel free to:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License.

## 🙏 Acknowledgments

- Built with [Google Cloud Speech-to-Text API](https://cloud.google.com/speech-to-text)
- Thanks to all the open-source projects that inspired this tool

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/wilsoncelyCUC">wilsoncelyCUC</a>
</p>
