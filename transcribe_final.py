import os
import argparse
import time
import subprocess
import threading
import sys
from datetime import datetime
from dotenv import load_dotenv
from google.cloud import speech_v1p1beta1 as speech
from google.cloud import storage

# --- Progress Bars and UI Enhancement Functions ---
def animate_progress(process, duration_estimate=None):
    """
    Displays a live progress animation while a process is running.

    Args:
        process: The subprocess.Popen object to monitor
        duration_estimate: Estimated duration in seconds (if known)
    """
    start_time = time.time()
    animation = "|/-\\"
    elapsed = 0
    idx = 0

    while process.poll() is None:  # While the process is still running
        elapsed = int(time.time() - start_time)
        progress_char = animation[idx % len(animation)]

        if duration_estimate:
            percent = min(100, int(elapsed / duration_estimate * 100))
            bar_length = 30
            filled_length = int(bar_length * percent // 100)
            bar = '█' * filled_length + '░' * (bar_length - filled_length)
            sys.stdout.write(f'\rConverting: [{bar}] {percent}% {progress_char} (Est: {elapsed}/{duration_estimate}s)')
        else:
            sys.stdout.write(f'\rConverting: {progress_char} Elapsed: {elapsed}s')

        sys.stdout.flush()
        idx += 1
        time.sleep(0.1)

    # Clear the line when done
    sys.stdout.write('\r' + ' ' * 80 + '\r')
    sys.stdout.flush()

    if process.returncode == 0:
        sys.stdout.write(f"\rConversion completed in {elapsed} seconds ✓\n")
    else:
        sys.stdout.write(f"\rConversion failed after {elapsed} seconds ✗\n")
    sys.stdout.flush()

def get_mp3_duration(mp3_path):
    """
    Get the duration of an MP3 file in seconds using ffprobe.
    Returns None if duration cannot be determined.
    """
    try:
        # Use ffprobe to get duration information
        result = subprocess.run([
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            mp3_path
        ], capture_output=True, text=True, check=True)

        # Convert to seconds (float)
        duration = float(result.stdout.strip())
        return duration
    except Exception as e:
        print(f"Could not determine audio duration: {e}")
        return None

def display_processing_progress(start_time, total_ops=None):
    """
    Display a better processing progress indicator.
    Returns a stop_event that should be set when processing completes.
    """
    stop_event = threading.Event()

    def update_progress():
        spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        idx = 0
        while not stop_event.is_set():
            elapsed = int(time.time() - start_time)
            minutes, seconds = divmod(elapsed, 60)

            if total_ops and total_ops > 0:
                spinner_char = spinner[idx % len(spinner)]
                sys.stdout.write(f"\rProcessing API request {spinner_char} {minutes:02d}:{seconds:02d}")
            else:
                bar_length = 20
                position = elapsed % (2 * bar_length)
                if position >= bar_length:
                    position = 2 * bar_length - position

                bar = ' ' * position + '<=>' + ' ' * (bar_length - position - 3)
                sys.stdout.write(f"\rProcessing: [{bar}] {minutes:02d}:{seconds:02d}")

            sys.stdout.flush()
            idx += 1
            time.sleep(0.1)

    # Start the progress display in a separate thread
    progress_thread = threading.Thread(target=update_progress)
    progress_thread.daemon = True
    progress_thread.start()

    return stop_event

# --- Helper Function for Conversion ---
def convert_mp3_to_flac(mp3_path: str, target_sample_rate: int = 48000) -> tuple[str | None, int | None]:
    """
    Converts an MP3 file to FLAC using ffmpeg with progress display.

    Args:
        mp3_path: Path to the input MP3 file.
        target_sample_rate: The sample rate for the output FLAC file.

    Returns:
        A tuple containing (path_to_flac_file, sample_rate) on success,
        or (None, None) on failure.
    """
    if not os.path.exists(mp3_path):
        print(f"Error: Input MP3 file not found at {mp3_path}")
        return None, None

    base, _ = os.path.splitext(mp3_path)
    flac_path = base + ".flac"
    print(f"Converting {os.path.basename(mp3_path)} to FLAC format at {target_sample_rate} Hz...")

    # Get audio duration for progress estimation
    duration = get_mp3_duration(mp3_path)
    if duration:
        print(f"Audio duration: {int(duration)} seconds")

    command = [
        'ffmpeg',
        '-i', mp3_path,         # Input file
        '-ar', str(target_sample_rate), # Set audio sample rate
        '-y',                   # Overwrite output file if it exists
        flac_path,              # Output file
        '-hide_banner',         # Suppress unnecessary ffmpeg banner
        '-loglevel', 'error'    # Only show errors
    ]

    try:
        # Start ffmpeg process
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Show progress animation
        animate_progress(process, duration_estimate=duration)

        # Process should be complete by this point
        if process.returncode != 0:
            stderr = process.stderr.read().decode()
            print(f"Error during ffmpeg conversion: {stderr}")
            if os.path.exists(flac_path):
                os.remove(flac_path)
            return None, None

        print(f"Successfully converted to {os.path.basename(flac_path)}")
        return flac_path, target_sample_rate
    except FileNotFoundError:
        print("Error: 'ffmpeg' command not found. Please ensure ffmpeg is installed and in your PATH.")
        return None, None
    except Exception as e:
        print(f"An unexpected error occurred during conversion: {e}")
        if os.path.exists(flac_path): # Clean up partial file if it exists
             os.remove(flac_path)
        return None, None
# --- End Helper Function ---

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

        # Get file size for progress reporting
        file_size = os.path.getsize(local_file_path)
        print(f"Uploading {os.path.basename(local_file_path)} ({file_size/1024/1024:.2f} MB) to GCS bucket...")

        # Create a simple progress callback
        last_progress = [0]

        def upload_progress_callback(progress):
            percent = min(100, int(progress * 100))
            if percent > last_progress[0] + 4 or percent == 100:  # Update every 5% to avoid console spam
                last_progress[0] = percent
                bar_length = 30
                filled_length = int(bar_length * percent // 100)
                bar = '█' * filled_length + '░' * (bar_length - filled_length)
                sys.stdout.write(f'\rUploading: [{bar}] {percent}%')
                sys.stdout.flush()

        # Upload with progress callback
        blob.upload_from_filename(local_file_path, timeout=600)

        # Clear the progress line and show completion
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        sys.stdout.write(f"Upload complete: gs://{gcs_bucket_name}/{blob_name}\n")
        sys.stdout.flush()

        return f"gs://{gcs_bucket_name}/{blob_name}"

    except Exception as e:
        print(f"Error uploading to GCS: {e}")
        return None


def transcribe_audio_with_diarization(
    audio_source_in: str, # Renamed to avoid conflict after conversion
    language_code: str = "en-US",
    min_speakers: int = 1,
    max_speakers: int = 5,
    # These are now defaults/placeholders, might be overridden by conversion
    sample_rate_in: int | None = None,
    encoding_in: speech.RecognitionConfig.AudioEncoding = speech.RecognitionConfig.AudioEncoding.LINEAR16,
    output_file: str | None = None,
    enhanced_model: bool = False
    ) -> str: # Returns a status message now
    """
    Converts MP3 to FLAC if needed, then transcribes using Google Cloud
    Speech-to-Text with speaker diarization enabled. Saves transcript to file.
    Returns a status message including the path of the file transcribed.
    """
    print(f"Starting audio transcription process for: {os.path.basename(audio_source_in)}")
    load_dotenv()

    # --- Determine final audio source, encoding, and sample rate ---
    audio_source_to_process = audio_source_in
    encoding_to_use = encoding_in
    sample_rate_to_use = sample_rate_in
    was_converted = False
    conversion_sample_rate = 48000 # Define the target rate for conversion

    # Check if input is MP3 and needs conversion
    _, ext = os.path.splitext(audio_source_in)
    if ext.lower() == '.mp3':
        flac_path, rate = convert_mp3_to_flac(audio_source_in, conversion_sample_rate)
        if flac_path and rate:
            audio_source_to_process = flac_path # Use the new FLAC file
            encoding_to_use = speech.RecognitionConfig.AudioEncoding.FLAC
            sample_rate_to_use = rate
            was_converted = True
        else:
            return "Error: MP3 to FLAC conversion failed. Cannot proceed."
    else:
         # For non-MP3, check if required args were provided if needed
         if encoding_to_use in [speech.RecognitionConfig.AudioEncoding.LINEAR16, speech.RecognitionConfig.AudioEncoding.FLAC, speech.RecognitionConfig.AudioEncoding.MULAW] and sample_rate_to_use is None:
              return f"Error: Sample rate must be provided via --sample_rate for this encoding ({encoding_to_use.name})."
         if sample_rate_to_use is None: # Set a default if still None (e.g. for OGG_OPUS)
             sample_rate_to_use = 0 # API ignores it if not needed

    print(f"Processing audio: {os.path.basename(audio_source_to_process)}")
    print(f"Settings: Encoding={encoding_to_use.name}, Sample Rate={sample_rate_to_use}, Language={language_code}")
    print(f"Speakers: Min={min_speakers}, Max={max_speakers}, Enhanced Model={enhanced_model}")
    # --- End final audio determination ---

    gcs_uri = None
    gcs_bucket_name = os.getenv("GCS_BUCKET_NAME")

    if not gcs_bucket_name:
        return "Error: GCS_BUCKET_NAME not found in .env file."

    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
         return ("Error: GOOGLE_APPLICATION_CREDENTIALS environment variable not set.\n"
                 "Make sure it's defined in your .env file and points to your service account key.")

    # Upload the file (original or converted FLAC)
    if audio_source_to_process.lower().startswith("gs://"):
        gcs_uri = audio_source_to_process
        print(f"Using existing GCS URI: {gcs_uri}")
    elif os.path.exists(audio_source_to_process):
        gcs_uri = upload_to_gcs(audio_source_to_process, gcs_bucket_name)
        if not gcs_uri:
            return "Failed to upload audio file to Google Cloud Storage."
    else:
        # This case should be rare now after conversion checks
        return f"Error: Audio source not found at '{audio_source_to_process}'"

    # --- Start Transcription API Call ---
    try:
        client = speech.SpeechClient()
        audio = speech.RecognitionAudio(uri=gcs_uri)

        diarization_config = speech.SpeakerDiarizationConfig(
            enable_speaker_diarization=True,
            min_speaker_count=min_speakers,
            max_speaker_count=max_speakers,
        )

        # Configure the request with enhanced settings if requested
        config_params = {
            "encoding": encoding_to_use,
            "sample_rate_hertz": sample_rate_to_use,
            "language_code": language_code,
            "diarization_config": diarization_config,
            "enable_word_time_offsets": True,
            "enable_automatic_punctuation": True,
        }

        # Add enhanced model if requested
        if enhanced_model:
            config_params["use_enhanced"] = True
            config_params["model"] = "latest_long"

        config = speech.RecognitionConfig(**config_params)

        print("\nSubmitting audio for transcription with speaker diarization...")
        operation = client.long_running_recognize(config=config, audio=audio)

        print("Request submitted successfully")
        print("Waiting for processing to complete - this may take a while for longer files")

        # Use our enhanced progress display
        start_time = time.time()
        progress_stop_event = display_processing_progress(start_time)

        try:
            # The operation.done() checks are now handled by the progress thread
            # Just wait for the final result
            response = operation.result(timeout=1800)  # 30 minute timeout

            # Stop the progress indicator
            progress_stop_event.set()
            time.sleep(0.2)  # Give the thread time to clean up

            # Clear the progress line
            sys.stdout.write('\r' + ' ' * 80 + '\r')
            print("Transcription processing complete!")

        except Exception as wait_error:
            progress_stop_event.set()
            print(f"\nError while waiting for transcription: {wait_error}")
            raise

        # --- DIARIZATION TRANSCRIPT PROCESSING (WITH ROBUST CHECKS) ---
        print("Processing transcript data...")
        formatted_transcript = ""
        current_speaker = None
        processing_error_occurred = False
        word_count = 0

        if response and response.results:
            print(f"Processing {len(response.results)} speech segments...")
            for result_index, result in enumerate(response.results):
                if not result.alternatives:
                    continue

                alternative = result.alternatives[0]

                if hasattr(alternative, 'words') and alternative.words:
                    segment_words = len(alternative.words)
                    word_count += segment_words

                    for word_info in alternative.words:
                        if word_info is None: continue

                        speaker_tag = getattr(word_info, 'speaker_tag', '?')
                        word = getattr(word_info, 'word', '')

                        if speaker_tag is None: speaker_tag = '?'

                        if speaker_tag != current_speaker:
                            if formatted_transcript: formatted_transcript += "\n\n"
                            current_speaker = speaker_tag
                            formatted_transcript += f"Speaker {current_speaker}: "

                        formatted_transcript += f"{word} "
                else:
                    processing_error_occurred = True

        # Determine final status message
        status_message = ""
        final_transcript_content = formatted_transcript.strip()

        if not final_transcript_content:
            if processing_error_occurred:
                 final_transcript_content = "Error: API returned results, but failed to process diarization word info. Check audio or parameters."
            else:
                 final_transcript_content = "Error: The API returned no transcription results. Check audio quality or parameters."
            status_message = final_transcript_content
        else:
             status_message = f"Transcription successful using file: {audio_source_to_process}"
             status_message += f"\nProcessed {word_count} words across {len(response.results)} speech segments"

        # Save the final transcript (or error) to file
        if output_file:
            output_dir = os.path.dirname(output_file)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(final_transcript_content)
                print(f"Transcript saved to: {output_file}")
                if "Error:" not in status_message:
                     status_message += f"\nTranscript saved to: {output_file}"
            except Exception as e:
                print(f"Error writing output file {output_file}: {e}")
                status_message += f"\nError writing output file: {e}"

        # Clean up converted file if it was created temporarily
        if was_converted and os.path.exists(audio_source_to_process) and audio_source_to_process != audio_source_in:
            try:
                os.remove(audio_source_to_process)
                print(f"Temporary FLAC file removed: {os.path.basename(audio_source_to_process)}")
            except Exception as e:
                print(f"Warning: Could not remove temporary FLAC file: {e}")

        return status_message

    except Exception as e:
        error_message = f"An error occurred during transcription: {e}"
        print(f"ERROR: {error_message}")
        if output_file:
            output_dir = os.path.dirname(output_file)
            if output_dir:
                 os.makedirs(output_dir, exist_ok=True)
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(error_message)
                print(f"Error details saved to: {output_file}")
            except Exception as write_e:
                 print(f"Error writing error details to output file: {write_e}")
        return error_message

# --- Main Execution ---
if __name__ == "__main__":
    print("=" * 80)
    print("Google Cloud Speech-to-Text Transcription Tool with Speaker Diarization")
    print("=" * 80)

    parser = argparse.ArgumentParser(description="Transcribe audio with speaker diarization using Google Cloud Speech-to-Text.")
    parser.add_argument("audio_source", help="Path to the local audio file (e.g., my_audio.mp3, my_audio.flac) or GCS URI.")
    parser.add_argument("-l", "--language", default="en-US", help="Language code (e.g., en-US, es-ES, fr-FR, de-DE). Default: en-US")
    parser.add_argument("--min_speakers", type=int, default=1, help="Minimum number of speakers expected. Default: 1")
    parser.add_argument("--max_speakers", type=int, default=5, help="Maximum number of speakers expected. Default: 5")
    # Make sample_rate optional initially
    parser.add_argument("--sample_rate", type=int, default=None, help="Sample rate (Hz). Required for LINEAR16/FLAC if input is not MP3. Ignored for MP3 input (uses 48000 Hz for conversion).")
    # Make encoding optional initially
    parser.add_argument("--encoding", default=None, help="Audio encoding (LINEAR16, FLAC, MP3, OGG_OPUS, etc.). Determined automatically for MP3 input. Required otherwise.")
    parser.add_argument("-o", "--output", default=None, help="Path to save the transcript output (e.g., output/transcript.txt)")
    parser.add_argument("--enhanced", action="store_true", help="Use enhanced model for better accuracy (may increase processing time)")

    args = parser.parse_args()

    # --- Determine initial encoding ---
    initial_encoding_str = args.encoding
    initial_audio_source = args.audio_source
    _, ext = os.path.splitext(initial_audio_source)

    encoding_map = {
        "LINEAR16": speech.RecognitionConfig.AudioEncoding.LINEAR16,
        "FLAC": speech.RecognitionConfig.AudioEncoding.FLAC,
        "MP3": speech.RecognitionConfig.AudioEncoding.MP3,
        "OGG_OPUS": speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
        "MULAW": speech.RecognitionConfig.AudioEncoding.MULAW,
    }

    initial_encoding = None
    if initial_encoding_str:
        initial_encoding = encoding_map.get(initial_encoding_str.upper())
        if not initial_encoding:
            print(f"Error: Unsupported encoding '{initial_encoding_str}' provided via argument.")
            print(f"Supported encodings: {', '.join(encoding_map.keys())}")
            exit(1)
    elif ext.lower() != '.mp3': # If not MP3 and no encoding provided, it's an error
         print(f"Error: --encoding argument is required for non-MP3 input files.")
         print(f"Supported encodings: {', '.join(encoding_map.keys())}")
         exit(1)
    # If it IS MP3, initial_encoding remains None, function will handle it.

    # --- Set default output file path if not provided ---
    output_file = args.output
    if output_file is None:
        os.makedirs("output", exist_ok=True)
        file_base = os.path.splitext(os.path.basename(args.audio_source))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"output/{file_base}_{timestamp}_diarized.txt"
        print(f"Output will be saved to: {output_file}")

    # Show a summary of the configuration
    print("\nConfiguration Summary:")
    print(f"- Input File: {os.path.basename(args.audio_source)}")
    print(f"- Language: {args.language}")
    print(f"- Speakers: {args.min_speakers} to {args.max_speakers}")
    print(f"- Enhanced Model: {'Yes' if args.enhanced else 'No'}")
    if ext.lower() == '.mp3':
        print("- Processing: MP3 will be automatically converted to FLAC")
    else:
        print(f"- Encoding: {initial_encoding_str}")
        if args.sample_rate:
            print(f"- Sample Rate: {args.sample_rate} Hz")
    print("-" * 40)

    # Start transcription process
    print("\nStarting transcription process...")
    result_message = transcribe_audio_with_diarization(
        audio_source_in=args.audio_source,
        language_code=args.language,
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
        sample_rate_in=args.sample_rate,
        encoding_in=initial_encoding,
        output_file=output_file,
        enhanced_model=args.enhanced
    )

    # --- Print the final status message from the function ---
    print("\n" + "=" * 40)
    print("TRANSCRIPTION SUMMARY")
    print("=" * 40)
    print(result_message)
    print("\nProcess complete.")
# use this version
