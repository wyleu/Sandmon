import numpy as np
import argparse
import librosa
from scipy import signal
import os
import logging
import time
import sys
import matplotlib.pyplot as plt
from pathlib import Path

# Set up logging

logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(threadName)s (%(thread)d): %(levelname)s - %(message)s',
	handlers=[
		logging.FileHandler('chunked_8.log'),
		logging.StreamHandler()
	]
	)
	
logger = logging.getLogger(__name__)
logger.info(f'Running {__name__}')


def calculate_rms(signal):
	"""Calculate RMS energy of a signal."""
	return np.sqrt(np.mean(signal**2))  # Correct RMS calculation

def print_if(verbose, *args, **kwargs):
	"""Print only if verbose is True (i.e., --short is not set)."""
	if verbose:
		print(*args, **kwargs)

import numpy as np
import librosa
from scipy import signal
import os
from pathlib import Path
import matplotlib.pyplot as plt
import logging
import time

def load_and_validate_audio(within_file, find_file, window, max_duration, sr_target=16000, verbose=True):
	"""Load audio files, validate durations, and log details."""
	try:
		# Log raw file durations
		raw_within_duration = librosa.get_duration(path=within_file)
		raw_find_duration = librosa.get_duration(path=find_file)
		raw_within_sr = librosa.get_samplerate(within_file)
		raw_find_sr = librosa.get_samplerate(find_file)
		logger.info(f"Raw recording ({within_file}): {raw_within_duration:.2f}s, sample rate: {raw_within_sr}Hz")
		logger.info(f"Raw template ({find_file}): {raw_find_duration:.2f}s, sample rate: {raw_find_sr}Hz")
		print_if(verbose, f"Raw recording: {raw_within_duration:.2f}s, {raw_within_sr}Hz")
		print_if(verbose, f"Raw template: {raw_find_duration:.2f}s, {raw_find_sr}Hz")

		# Validate raw durations
		if raw_find_duration < window * 0.9:
			raise ValueError(f"Raw template duration ({raw_find_duration:.2f}s) is shorter than expected window ({window}s)")
		if raw_within_duration < max_duration * 0.9:
			logger.warning(f"Raw recording duration ({raw_within_duration:.2f}s) is shorter than expected ({max_duration}s)")

		# Load audio at target sample rate
		logger.info(f"Loading {within_file} and {find_file} at {sr_target}Hz")
		start_time = time.time()
		y_within, sr_within = librosa.load(within_file, sr=sr_target, mono=True, duration=max_duration)
		y_find, _ = librosa.load(find_file, sr=sr_target, mono=True, duration=window)
		y_find = y_find[:int(sr_target * window)]

		# Log processed durations
		within_duration = len(y_within) / sr_within
		find_duration = len(y_find) / sr_within
		logger.info(f"Processed recording ({within_file}): {within_duration:.2f}s, {len(y_within)} samples, sample rate: {sr_within}Hz")
		logger.info(f"Processed template ({find_file}): {find_duration:.2f}s, {len(y_find)} samples, sample rate: {sr_within}Hz")
		print_if(verbose, f"Processed recording: {within_duration:.2f}s, {len(y_within)} samples")
		print_if(verbose, f"Processed template: {find_duration:.2f}s, {len(y_find)} samples")
		print_if(verbose, f"Audio loaded in {time.time() - start_time:.2f}s")

		# Validate processed durations
		if find_duration < window * 0.9:
			raise ValueError(f"Processed template duration ({find_duration:.2f}s) is shorter than window ({window}s)")
		if sr_within != sr_target:
			raise ValueError(f"Sample rate mismatch: got {sr_within}Hz, expected {sr_target}Hz")

		return y_within, y_find, sr_within, within_duration
	except Exception as e:
		logger.error(f"Error loading audio files: {e} Line: {e.__traceback__.tb_lineno}")
		print(f"Error: {e} Line: {e.__traceback__.tb_lineno}")
		return None, None, None, None

def compute_chunk_rms(y_within, sr_within, chunk_duration, window, verbose=True):
	"""Compute RMS for audio chunks and check for similarity."""
	chunk_samples = int(chunk_duration * sr_within)
	overlap_samples = int(window * sr_within)
	step_size = chunk_samples - overlap_samples
	if step_size <= 0:
		raise ValueError(
			f"Chunk duration ({chunk_duration}s, {chunk_samples} samples) must be greater than "
			f"window ({window}s, {overlap_samples} samples) at sample rate {sr_within}Hz"
		)

	num_chunks = max(1, (len(y_within) - overlap_samples) // step_size + 1)
	logger.info(f"Computing RMS for {num_chunks} chunks of {chunk_duration}s each")

	chunk_rms = []
	for i in range(num_chunks):
		chunk_start = i * step_size
		chunk_end = min(chunk_start + chunk_samples, len(y_within))
		chunk = y_within[chunk_start:chunk_end]
		chunk_duration_actual = (chunk_end - chunk_start) / sr_within
		if len(chunk) < int(window * sr_within):
			logger.warning(f"Chunk {i+1}/{num_chunks} too small: {chunk_duration_actual:.2f}s, {len(chunk)} samples, skipping")
			continue
		rms = calculate_rms(chunk)
		chunk_rms.append((i, rms, chunk_start, chunk_end))
		logger.info(f"Chunk {i+1}/{num_chunks}: {chunk_duration_actual:.2f}s, {len(chunk)} samples, RMS: {rms:.4f}")

	if chunk_rms:
		rms_values = [rms for _, rms, _, _ in chunk_rms]
		rms_std = np.std(rms_values)
		rms_std_threshold = 0.0001  # Adjust based on testing
		logger.info(f"RMS standard deviation: {rms_std:.6f}")
		if rms_std < rms_std_threshold:
			logger.warning(f"No match: RMS values too similar (std: {rms_std:.6f} < {rms_std_threshold})")
			print_if(verbose, "No match: RMS values too similar")
			return None, None  # Return tuple to maintain consistent return type
	else:
		logger.error("No valid chunks for RMS calculation")
		print_if(verbose, "Error: No valid chunks for RMS calculation")
		return None, None  # Return tuple to maintain consistent return type

	return chunk_rms, num_chunks

def correlate_top_chunks(y_within, y_find, chunk_rms, num_chunks, top_n_chunks, sr_within, verbose=True, corr_method='fft'):
	"""Perform cross-correlation on top N chunks with highest RMS and store correlation data."""
	chunk_rms.sort(key=lambda x: x[1], reverse=True)
	top_chunks = chunk_rms[:min(top_n_chunks, len(chunk_rms))]
	logger.info(f"Selected top {len(top_chunks)} chunks with highest RMS")

	max_peak = -np.inf
	max_offset = 0
	chunks_processed = 0
	correlation_data = []  # Store (correlation_array, chunk_start) for visualization

	for i, rms, chunk_start, chunk_end in top_chunks:
		chunk = y_within[chunk_start:chunk_end]
		logger.info(f"Correlating chunk {i+1}/{num_chunks} (RMS: {rms:.4f})")
		chunk_start_time = time.time()
		c = signal.correlate(chunk, y_find, mode='valid', method=corr_method)
		chunk_peak = np.max(c)
		chunk_peak_idx = np.argmax(c)
		correlation_data.append((c, chunk_start))  # Store for visualization
		global_offset = chunk_start + chunk_peak_idx
		if chunk_peak > max_peak:
			max_peak = chunk_peak
			max_offset = global_offset
		chunk_time = time.time() - chunk_start_time
		chunks_processed += 1
		logger.info(f"Chunk {i+1}/{num_chunks} completed in {chunk_time:.2f}s")

	if chunks_processed == 0:
		logger.error("No chunks processed (all too small or low RMS)")
		print("Error: No chunks processed")
		return None, None, None

	return max_offset, chunks_processed, correlation_data

def generate_visualization(y_within, y_find, within_duration, max_offset, sr_within, within_file, find_file, correlation_data, verbose=True):
	"""Generate a single PNG with aligned full audio, template, and correlation using chunk data."""
	logger.info("Generating visualization using chunk correlation data")
	find_duration = len(y_find) / sr_within
	offset = round(max_offset / sr_within, 2)
	
	fig, (ax_full, ax_template, ax_corr) = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
	t_within = np.linspace(0, within_duration, len(y_within))
	t_template = np.linspace(0, find_duration, len(y_find))
	
	ax_full.plot(t_within, y_within, label='Full Audio')
	ax_full.set_title(f'Full Recording ({Path(within_file).name})')
	ax_full.set_ylabel('Amplitude')
	ax_full.grid(True)
	
	template_start_time = max_offset / sr_within
	t_template_shifted = t_template + template_start_time
	ax_template.plot(t_template_shifted, y_find, label='Template', color='orange')
	ax_template.set_title(f'Template ({Path(find_file).name}) at Offset {offset}s')
	ax_template.set_ylabel('Amplitude')
	ax_template.grid(True)
	
	for c, chunk_start in correlation_data:
		corr_length = len(c)
		t_corr = np.linspace(chunk_start / sr_within, (chunk_start + corr_length - 1) / sr_within, corr_length)
		ax_corr.plot(t_corr, c, label='Correlation (Chunk)', color='green', alpha=0.5)
	
	ax_corr.axvline(x=offset, color='red', linestyle='--', label=f'Peak at {offset}s')
	ax_corr.set_title('Cross-Correlation (Chunked)')
	ax_corr.set_xlabel('Time (s)')
	ax_corr.set_ylabel('Correlation')
	ax_corr.grid(True)
	ax_corr.legend()
	
	output_file = os.path.join(os.path.dirname(within_file), f'{Path(within_file).stem}_aligned.png')
	fig.tight_layout()
	plt.savefig(output_file, dpi=300, bbox_inches='tight')
	plt.close()
	logger.info(f"Saved visualization to {output_file}")

def find_offset(within_file, find_file, window=12, max_duration=240, chunk_duration=30, top_n_chunks=2, verbose=True):
	"""Find offset of template in recording using chunked cross-correlation with RMS pre-screening."""
	try:
		start_time = time.time()
		logger.info(f"Starting offset calculation for {find_file} in {within_file}")

		# Load and validate audio
		y_within, y_find, sr_within, within_duration = load_and_validate_audio(
			within_file, find_file, window, max_duration, verbose=verbose
		)
		
		logger.info(f'Parameters to compute_chunk_rms y_within: {len(y_within)}, sr_within: {sr_within}, chunk_duration: {chunk_duration}, window {window}')
		
		if y_within is None or y_find is None:
			logger.error("Failed to load audio files")
			print_if(verbose, "Error: Failed to load audio files")
			return None
		
		# Compute RMS for chunks
		chunk_rms, num_chunks = compute_chunk_rms(y_within, sr_within, chunk_duration, window, verbose=verbose)
		if chunk_rms is None:
			logger.error("No valid chunks or RMS values too similar, cannot compute offset")
			print_if(verbose, "Error: No valid chunks or RMS values too similar")
			return None

		# Correlate top chunks
		max_offset, chunks_processed, correlation_data = correlate_top_chunks(
			y_within, y_find, chunk_rms, num_chunks, top_n_chunks, sr_within, verbose=verbose
		)
		if max_offset is None:
			logger.error("No valid correlation data from chunks")
			print_if(verbose, "Error: No valid correlation data")
			return None

		# Calculate final offset and accuracy
		offset = round(max_offset / sr_within, 2)
		accuracy = offset - 120  # Expected 2 minutes into 4-minute recording
		total_time = time.time() - start_time
		logger.info(f"Offset: {offset}s, Accuracy: {accuracy:+.2f}s, Time: {total_time:.2f}s")
		print_if(verbose, f"Offset: {offset}s\nClock accuracy: {accuracy:+.2f}s")

		# Generate visualization
		generate_visualization(y_within, y_find, within_duration, max_offset, sr_within, within_file, find_file, correlation_data, verbose)

		return offset
	except Exception as e:
		logger.error(f"Error processing {within_file} or {find_file}: {e} Line: {e.__traceback__.tb_lineno}")
		print_if(verbose, f"Error: {e} Line: {e.__traceback__.tb_lineno}")
		return None

def main():
	parser = argparse.ArgumentParser(description="Find offset of template in clock strike recording")
	parser.add_argument('--find-offset-of', metavar='audio file', type=str, required=True, help='Template WAV file (e.g., 12s clock strike)')
	parser.add_argument('--within', metavar='audio file', type=str, required=True, help='Recording WAV file (e.g., 4min clock recording)')
	parser.add_argument('--window', metavar='seconds', type=int, default=12, help='Template duration in seconds (default: 12)')
	parser.add_argument('--batch', action='store_true', help='Process all WAV files in directory')
	parser.add_argument('--directory', metavar='directory', type=str, default='.', help='Directory containing WAV files for batch processing (default: current directory)')
	parser.add_argument('--chunk-duration', metavar='seconds', type=int, default=30, help='Chunk duration in seconds (default: 30, must be >= window + 3)')
	parser.add_argument('--top-n-chunks', metavar='N', type=int, default=2, help='Number of high-RMS chunks to process (default: 2)')
	parser.add_argument('--short', action='store_true', help='Short output (offset and accuracy only)')
	parser.add_argument('--sample-rate', type=int, default=16000, help='Target sample rate in Hz (default: 16000)')
	parser.add_argument('--corr-method', choices=['direct', 'fft'], default='fft', help='Correlation method (default: fft)')
	args = parser.parse_args()
	args.max_duration = 240
	template_path = './'
	
	# Log command-line arguments
	logger.info(f"Command-line arguments: {vars(args)}")
	print_if(not args.short, f"Command-line arguments: {vars(args)}")

	# Validate directory
	if not os.path.isdir(args.directory):
		logger.error(f"Directory {args.directory} does not exist")
		print(f"Error: Directory {args.directory} does not exist")
		return

	# Construct full paths for input files
	within_file = os.path.join(args.directory, args.within) if not os.path.isabs(args.within) else args.within
	find_file = os.path.join(template_path, args.find_offset_of) if not os.path.isabs(args.find_offset_of) else args.find_offset_of

	# Validate input files
	if not os.path.exists(within_file):
		logger.error(f"File {within_file} does not exist")
		print(f"Error: File {within_file} does not exist")
		return
	if not os.path.exists(find_file):
		logger.error(f"File {find_file} does not exist")
		print(f"Error: File {find_file} does not exist")
		return

	# Validate and adjust chunk duration
	min_chunk_duration = args.window + 3
	if args.chunk_duration < min_chunk_duration:
		logger.warning(
			f"Chunk duration ({args.chunk_duration}s) is too small for window ({args.window}s). "
			f"Adjusting to {min_chunk_duration}s"
		)
		print_if(not args.short, f"Warning: Chunk duration ({args.chunk_duration}s) too small, adjusting to {min_chunk_duration}s")
		args.chunk_duration = min_chunk_duration

	verbose = not args.short
	if args.batch:
		logger.info("Starting batch processing")
		wav_files = [f for f in os.listdir(args.directory) if f.endswith(".wav") and f != args.find_offset_of]
		total_files = len(wav_files)
		logger.info(f"Found {total_files} WAV files to process in {args.directory}")
		
		for i, wavfile in enumerate(wav_files, 1):
			wavfile_path = os.path.join(args.directory, wavfile)
			logger.info(f"Processing file {i}/{total_files}: {wavfile}")
			offset = find_offset(within_file, wavfile_path, args.window, args.max_duration, args.chunk_duration, args.top_n_chunks, verbose)
			if offset is not None:
				logger.info(f"Completed {wavfile}: Offset {offset}s")
				logger.info(f"{wavfile}: Offset: {offset}s, Accuracy: {(offset - 120):+.2f}s")
			else:
				logger.warning(f"Failed to process {wavfile}")
	else:
		logger.info(f"Processing single file: {find_file}")
		offset = find_offset(within_file, find_file, args.window, args.max_duration, args.chunk_duration, args.top_n_chunks, verbose)
		if offset is not None:
			logger.info(f"Completed {find_file}: Offset {offset}s")
		else:
			logger.warning(f"Failed to process {find_file}")

if __name__ == '__main__':
	main()
	
	# "python chunked_8.py --find-offset-of normalized_hour_strike_preamble.wav --within recordings/20250807/recording_20250807_100202.wav"
