import os
import argparse
import time
from dotenv import load_dotenv
from google.cloud import speech_v1p1beta1 as speech
from google.cloud import storage

def upload_to_gcs(local_file_path: str, gcs_bucket_name: str) -> str:
    """Uploads a file to Google Cloud Storage and returns the GCS URI."""
    try:
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
             print("Error: GOOGLE_APPLICATION_CREDENTIALS environment variable not set.")
             print("Make sure it's defined in your .env file and points to your service account key.")
             return None

        storage_client = storage.Client()
        bucket = storage_client.bucket(gcs_bucket_name)

        blob_name = f"audio_uploads/{os.path.basename(local_file_path)}_{int(time.time())}"
        blob = bucket.blob(blob_name)

        print(f"Uploading {local_file_path} to gs://{gcs_bucket_name}/{blob_name}...")
        blob.upload_from_filename(local_file_path)
        print("Upload complete.")

        return f"gs://{gcs_bucket_name}/{blob_name}"

    except Exception as e:
        print(f"Error uploading to GCS: {e}")
        return None

def transcribe_audio_with_diarization( # Function name kept for consistency
    audio_source: str,
    language_code: str = "en-US",
    # min_speakers and max_speakers arguments are ignored when diarization is disabled below
    min_speakers: int = 1,
    max_speakers: int = 5,
    sample_rate: int = 16000,
    encoding: speech.RecognitionConfig.AudioEncoding = speech.RecognitionConfig.AudioEncoding.LINEAR16,
    output_file: str = None
    ) -> str:
    """
    Transcribes audio using Google Cloud Speech-to-Text.
    NOTE: Diarization is currently DISABLED in this version for troubleshooting.
    """
    print(f"DEBUG: Entering transcribe_audio_with_diarization (DIARIZATION DISABLED) with source: {audio_source}") # <-- DEBUG
    load_dotenv()
    print("DEBUG: dotenv loaded (or attempted).") # <-- DEBUG

    gcs_uri = None
    gcs_bucket_name = os.getenv("GCS_BUCKET_NAME")

    if not gcs_bucket_name:
        return "Error: GCS_BUCKET_NAME not found in .env file."

    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
         return ("Error: GOOGLE_APPLICATION_CREDENTIALS environment variable not set.\n"
                 "Make sure it's defined in your .env file and points to your service account key.")

    if audio_source.lower().startswith("gs://"):
        gcs_uri = audio_source
        print(f"Using existing GCS URI: {gcs_uri}")
    elif os.path.exists(audio_source):
        print(f"Local file detected: {audio_source}")
        gcs_uri = upload_to_gcs(audio_source, gcs_bucket_name)
        if not gcs_uri:
            return "Failed to upload audio file to Google Cloud Storage."
    else:
        return f"Error: Audio source not found at '{audio_source}'"

    try:
        client = speech.SpeechClient()
        audio = speech.RecognitionAudio(uri=gcs_uri)

        # --- DIARIZATION DISABLED ---
        # diarization_config = speech.SpeakerDiarizationConfig(
        #     enable_speaker_diarization=True,
        #     min_speaker_count=min_speakers,
        #     max_speaker_count=max_speakers,
        # )
        # --- DIARIZATION DISABLED ---

        # Configure the request WITHOUT diarization
        config = speech.RecognitionConfig(
            encoding=encoding,
            sample_rate_hertz=sample_rate, # Ignored for MP3 by API
            language_code=language_code,
            # diarization_config=diarization_config,  # <-- DIARIZATION DISABLED
            # enable_word_time_offsets=True,          # <-- DIARIZATION DISABLED (Optional for basic transcript)
            enable_automatic_punctuation=True
        )

        print("Starting asynchronous transcription request (Diarization Disabled)...")
        operation = client.long_running_recognize(config=config, audio=audio)

        print("Waiting for operation to complete...")
        # Timeout kept long just in case
        response = operation.result(timeout=1800)
        print("Transcription complete.")

        # --- BASIC TRANSCRIPT PROCESSING (NO DIARIZATION) ---
        formatted_transcript = ""
        if response.results:
            # Get the first alternative of the last result (most likely final transcript)
            final_result = response.results[-1]
            if final_result.alternatives:
                if final_result.alternatives[0].transcript:
                    formatted_transcript = final_result.alternatives[0].transcript
                else:
                     formatted_transcript = "Error: API returned alternatives but no transcript text."
            else:
                formatted_transcript = "Error: The API returned results but no transcription alternatives."
        else:
            # This was the error you were getting before
            formatted_transcript = "Error: The API returned no transcription results. Check audio quality or parameters."
        # --- END BASIC TRANSCRIPT PROCESSING ---

        # Save the transcript to file if output_file is provided
        if output_file:
            # Create the directory if it doesn't exist
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, 'w') as f:
                f.write(formatted_transcript)
            print(f"Transcription saved to: {output_file}")

        return formatted_transcript # Return the plain transcript (or error)

    except Exception as e:
        error_message = f"An error occurred during transcription: {e}"
        # Optionally save the error to the output file too
        if output_file:
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, 'w') as f:
                f.write(error_message)
            print(f"Error saved to: {output_file}")
        return error_message

# --- Main Execution ---
if __name__ == "__main__":
    print("DEBUG: Starting main execution block.") # <-- DEBUG
    parser = argparse.ArgumentParser(description="Transcribe audio (DIARIZATION DISABLED) using Google Cloud Speech-to-Text.")
    parser.add_argument("audio_source", help="Path to the local audio file (e.g., my_audio.wav) or GCS URI (gs://bucket/object).")
    parser.add_argument("-l", "--language", default="en-US", help="Language code (e.g., en-US, es-ES). Default: en-US")
    # Speaker args are kept for interface consistency but ignored by the function now
    parser.add_argument("--min_speakers", type=int, default=1, help="Minimum number of speakers expected (IGNORED). Default: 1")
    parser.add_argument("--max_speakers", type=int, default=5, help="Maximum number of speakers expected (IGNORED). Default: 5")
    parser.add_argument("--sample_rate", type=int, default=None, help="Sample rate of the audio in Hz (e.g., 16000, 44100). Often ignored for MP3/OGG_OPUS. Default: None")
    parser.add_argument("--encoding", default="LINEAR16", help="Audio encoding (LINEAR16, FLAC, MP3, OGG_OPUS, etc.). Default: LINEAR16 (for WAV)")
    # Add new argument for output file
    parser.add_argument("-o", "--output", default=None, help="Path to save the transcript output (e.g., output/transcript.txt)")

    args = parser.parse_args()
    print(f"DEBUG: Arguments parsed: {args}") # <-- DEBUG

    encoding_map = {
        "LINEAR16": speech.RecognitionConfig.AudioEncoding.LINEAR16,
        "FLAC": speech.RecognitionConfig.AudioEncoding.FLAC,
        "MP3": speech.RecognitionConfig.AudioEncoding.MP3,
        "OGG_OPUS": speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
        "MULAW": speech.RecognitionConfig.AudioEncoding.MULAW,
    }
    audio_encoding = encoding_map.get(args.encoding.upper())
    if not audio_encoding:
        print(f"Error: Unsupported encoding '{args.encoding}'. Supported: {list(encoding_map.keys())}")
        exit(1)

    sample_rate_hertz = args.sample_rate
    if audio_encoding in [speech.RecognitionConfig.AudioEncoding.LINEAR16, speech.RecognitionConfig.AudioEncoding.FLAC, speech.RecognitionConfig.AudioEncoding.MULAW] and sample_rate_hertz is None:
         print(f"Error: Sample rate must be provided using --sample_rate for encoding {args.encoding}.")
         exit(1)

    # Set default output file path if not provided
    output_file = args.output
    if not output_file:
        # Create output directory if it doesn't exist
        os.makedirs("output", exist_ok=True)
        # Generate output filename based on input filename
        file_base = os.path.splitext(os.path.basename(args.audio_source))[0]
        output_file = f"output/{file_base}_transcript.txt"
        print(f"No output file specified. Will save to: {output_file}")

    print("DEBUG: Calling transcribe_audio_with_diarization (DIARIZATION DISABLED)...") # <-- DEBUG
    transcription = transcribe_audio_with_diarization(
        audio_source=args.audio_source,
        language_code=args.language,
        # min/max speakers are passed but ignored inside the function now
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
        sample_rate=sample_rate_hertz if sample_rate_hertz is not None else 0,
        encoding=audio_encoding,
        output_file=output_file
    )

    print(f"DEBUG: Transcription function returned: {transcription[:500]}...") # <-- DEBUG
    print("\n--- Transcription Result (Diarization Disabled) ---")
    print(transcription)
