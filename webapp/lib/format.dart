// Formatting helpers mirroring qbit_bot/utils.py so both UIs read the same.

String fmtSize(num n) {
  var v = n.toDouble();
  for (final unit in const ['B', 'KiB', 'MiB', 'GiB', 'TiB']) {
    if (v < 1024) {
      return '${v.toStringAsFixed(v < 10 && unit != 'B' ? 2 : 1)} $unit';
    }
    v /= 1024;
  }
  return '${v.toStringAsFixed(1)} PiB';
}

String fmtSpeed(num bytesPerSec) => '${fmtSize(bytesPerSec)}/s';

String fmtEta(int seconds) {
  if (seconds >= 8640000 || seconds < 0) return '∞';
  final m = seconds ~/ 60;
  final h = m ~/ 60;
  final d = h ~/ 24;
  if (d > 0) return '${d}d ${h % 24}h';
  if (h > 0) return '${h}h ${m % 60}m';
  return '${m}m';
}

String fmtPercent(double fraction) =>
    '${(fraction * 100).toStringAsFixed(fraction >= 1 ? 0 : 1)}%';

String fmtAgo(DateTime t) {
  final d = DateTime.now().difference(t);
  if (d.inMinutes < 1) return 'just now';
  if (d.inMinutes < 120) return '${d.inMinutes} min ago';
  if (d.inHours < 48) return '${d.inHours} h ago';
  return '${d.inDays} d ago';
}

String fmtDateTime(DateTime t) {
  String two(int n) => n.toString().padLeft(2, '0');
  final now = DateTime.now();
  final sameDay =
      t.year == now.year && t.month == now.month && t.day == now.day;
  final time = '${two(t.hour)}:${two(t.minute)}';
  return sameDay ? time : '${two(t.day)}/${two(t.month)} $time';
}

const stateEmoji = <String, String>{
  'downloading': '⬇️',
  'forcedDL': '⬇️',
  'metaDL': '🔍',
  'allocating': '⏳',
  'uploading': '🌱',
  'forcedUP': '🌱',
  'stalledUP': '✅',
  'stalledDL': '🐌',
  'pausedDL': '⏸',
  'stoppedDL': '⏸',
  'pausedUP': '☑️',
  'stoppedUP': '☑️',
  'queuedDL': '🕐',
  'queuedUP': '🕐',
  'checkingDL': '🔬',
  'checkingUP': '🔬',
  'checkingResumeData': '🔬',
  'error': '❌',
  'missingFiles': '❌',
  'moving': '📦',
};

const stateLabel = <String, String>{
  'downloading': 'Downloading',
  'forcedDL': 'Downloading (forced)',
  'metaDL': 'Fetching metadata',
  'allocating': 'Allocating',
  'uploading': 'Seeding',
  'forcedUP': 'Seeding (forced)',
  'stalledUP': 'Complete',
  'stalledDL': 'Stalled',
  'pausedDL': 'Paused',
  'stoppedDL': 'Stopped',
  'pausedUP': 'Paused (complete)',
  'stoppedUP': 'Stopped (complete)',
  'queuedDL': 'Queued',
  'queuedUP': 'Queued (seeding)',
  'checkingDL': 'Checking',
  'checkingUP': 'Checking',
  'checkingResumeData': 'Checking resume data',
  'error': 'Error',
  'missingFiles': 'Missing files',
  'moving': 'Moving files',
};

String stateIcon(String state) => stateEmoji[state] ?? '❓';
String stateName(String state) => stateLabel[state] ?? state;
