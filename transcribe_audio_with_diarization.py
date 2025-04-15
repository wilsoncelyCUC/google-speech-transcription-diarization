
import os
import argparse
import time
from datetime import datetime # Needed for timestamp
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

def transcribe_audio_with_diarization(
    audio_source: str,
    language_code: str = "en-US",
    min_speakers: int = 1,
    max_speakers: int = 5,
    sample_rate: int = 16000,
    encoding: speech.RecognitionConfig.AudioEncoding = speech.RecognitionConfig.AudioEncoding.LINEAR16,
    output_file: str = None
    ) -> str:
    """
    Transcribes audio using Google Cloud Speech-to-Text with speaker diarization enabled.
    Includes robust checks for None in response processing.
    """
    print(f"DEBUG: Entering transcribe_audio_with_diarization with source: {audio_source}")
    load_dotenv()
    print("DEBUG: dotenv loaded (or attempted).")

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

        # --- DIARIZATION ENABLED ---
        diarization_config = speech.SpeakerDiarizationConfig(
            enable_speaker_diarization=True,
            min_speaker_count=min_speakers,
            max_speaker_count=max_speakers,
        )
        # --- DIARIZATION ENABLED ---

        # Configure the request WITH diarization
        config = speech.RecognitionConfig(
            encoding=encoding,
            sample_rate_hertz=sample_rate, # Ignored for MP3 by API
            language_code=language_code,
            diarization_config=diarization_config,
            enable_word_time_offsets=True,
            enable_automatic_punctuation=True
        )

        print("Starting asynchronous transcription request (WITH Speaker Diarization)...")
        operation = client.long_running_recognize(config=config, audio=audio)

        print("Waiting for operation to complete...")
        print("(This may take several minutes for longer audio files)")

        # Use simpler progress indicator based on elapsed time
        start_time = time.time()
        done = False

        while not done:
            elapsed = int(time.time() - start_time)
            print(f"Processing... (elapsed time: {elapsed} seconds)", end="\r")

            # Check if operation is done
            try:
                # Check done status without relying on metadata()
                done = operation.done()
            except Exception as e:
                 # Handle potential errors checking status, but try to proceed to result()
                 print(f"\nWarning: Error checking operation status ({e}). Will attempt to get result anyway.")
                 break # Exit loop and attempt to get result

            if not done:
                time.sleep(10) # Check every 10 seconds

        print("\nTranscription processing finished. Getting results...")
        response = operation.result(timeout=1800) # Wait up to 30 mins for result retrieval if needed
        print("Transcription complete.")

        # --- DIARIZATION TRANSCRIPT PROCESSING (WITH ROBUST CHECKS) ---
        formatted_transcript = ""
        current_speaker = None

        # Check if response and results exist
        if response and response.results:
            print(f"DEBUG: Processing {len(response.results)} result(s).")
            for result_index, result in enumerate(response.results):
                # Check if alternatives exist
                if not result.alternatives:
                    print(f"DEBUG: Result {result_index} has no alternatives.")
                    continue

                alternative = result.alternatives[0]
                print(f"DEBUG: Processing alternative 0 from result {result_index}.")

                # Check if words exist before iterating
                if hasattr(alternative, 'words') and alternative.words:
                    print(f"DEBUG: Found {len(alternative.words)} words in alternative.")
                    for word_info in alternative.words:
                        # Check if word_info is not None (highly unlikely but safe)
                        if word_info is None:
                            continue

                        # Use getattr for safer attribute access, providing defaults
                        speaker_tag = getattr(word_info, 'speaker_tag', None)
                        word = getattr(word_info, 'word', '')

                        # If speaker tag is None (shouldn't happen with diarization but check), assign placeholder
                        if speaker_tag is None:
                           speaker_tag = '?'

                        # If speaker tag changes, add a new line with speaker label
                        if speaker_tag != current_speaker:
                            # Avoid adding extra newline at the very beginning
                            if formatted_transcript:
                                formatted_transcript += "\n\n"
                            current_speaker = speaker_tag
                            formatted_transcript += f"Speaker {current_speaker}: "

                        # Add the word to the transcript
                        formatted_transcript += f"{word} "
                else:
                    # Handle case where alternative exists but has no words
                    print(f"Warning: Result {result_index} alternative 0 found, but it contains no word data.")
                    # Optionally add the full transcript if available and word info is missing
                    # if alternative.transcript:
                    #    if formatted_transcript: formatted_transcript += "\n" # Add separator
                    #    formatted_transcript += f"(Full segment transcript: {alternative.transcript})"

        # If no valid transcript content was generated after processing all results
        if not formatted_transcript.strip(): # Check if it's empty or just whitespace/newlines
            if response and response.results:
                 formatted_transcript = "Error: API returned results, but failed to process diarization word info. Check audio or parameters."
            else:
                 formatted_transcript = "Error: The API returned no transcription results. Check audio quality or parameters."
        # --- END PROCESSING WITH CHECKS ---


        # Save the transcript to file if output_file is provided
        if output_file:
            # Ensure directory exists
            output_dir = os.path.dirname(output_file)
            if output_dir: # Only create if not saving to current directory
                os.makedirs(output_dir, exist_ok=True)
            try:
                with open(output_file, 'w', encoding='utf-8') as f: # Use utf-8 encoding
                    f.write(formatted_transcript.strip()) # Write stripped transcript
                print(f"Transcription output saved to: {output_file}")
            except Exception as e:
                print(f"Error writing output file {output_file}: {e}")


        return formatted_transcript.strip() # Return the formatted transcript (or error)

    except Exception as e:
        error_message = f"An error occurred during transcription: {e}"
        print(f"DEBUG: Exception caught: {error_message}") # Print exception details
        # Optionally save the error to the output file too
        if output_file:
            output_dir = os.path.dirname(output_file)
            if output_dir:
                 os.makedirs(output_dir, exist_ok=True)
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(error_message)
                print(f"Error details saved to: {output_file}")
            except Exception as write_e:
                 print(f"Error writing error details to output file {output_file}: {write_e}")
        return error_message

# --- Main Execution ---
if __name__ == "__main__":
    print("DEBUG: Starting main execution block.")
    parser = argparse.ArgumentParser(description="Transcribe audio with speaker diarization using Google Cloud Speech-to-Text.")
    parser.add_argument("audio_source", help="Path to the local audio file (e.g., my_audio.wav) or GCS URI (gs://bucket/object).")
    parser.add_argument("-l", "--language", default="en-US", help="Language code (e.g., en-US, es-ES). Default: en-US")
    parser.add_argument("--min_speakers", type=int, default=1, help="Minimum number of speakers expected. Default: 1")
    parser.add_argument("--max_speakers", type=int, default=5, help="Maximum number of speakers expected. Default: 5")
    parser.add_argument("--sample_rate", type=int, default=None, help="Sample rate of the audio in Hz (e.g., 16000, 44100). Often ignored for MP3/OGG_OPUS. Default: None")
    parser.add_argument("--encoding", default="LINEAR16", help="Audio encoding (LINEAR16, FLAC, MP3, OGG_OPUS, etc.). Default: LINEAR16 (for WAV)")
    # Add new argument for output file
    parser.add_argument("-o", "--output", default=None, help="Path to save the transcript output (e.g., output/transcript.txt)")

    args = parser.parse_args()
    print(f"DEBUG: Arguments parsed: {args}")

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
    if output_file is None: # Explicitly check for None
        # Create output directory if it doesn't exist
        os.makedirs("output", exist_ok=True)
        # Generate output filename based on input filename
        file_base = os.path.splitext(os.path.basename(args.audio_source))[0]
        # --- ADD TIMESTAMP TO DEFAULT FILENAME ---
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"output/{file_base}_{timestamp}_diarized.txt"
        # --- TIMESTAMP ADDED ---
        print(f"No output file specified. Will save to: {output_file}")

    print("DEBUG: Calling transcribe_audio_with_diarization...")
    transcription = transcribe_audio_with_diarization(
        audio_source=args.audio_source,
        language_code=args.language,
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
        sample_rate=sample_rate_hertz if sample_rate_hertz is not None else 0,
        encoding=audio_encoding,
        output_file=output_file
    )

    # Print first 500 chars of result/error for debug log
    print(f"DEBUG: Transcription function returned: {transcription[:500]}...")
    print("\n--- Transcription Result (WITH Speaker Diarization) ---")
    # Print the full result (which might be an error message)
    print(transcription)
