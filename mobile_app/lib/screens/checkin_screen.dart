import 'package:flutter/material.dart';

import '../services/api_client.dart';

/// "How did you sleep?" check-in screen.
///
/// Each answer is a noisy observation of whether the user's room crossed the
/// recovery threshold last night. The backend folds these into a per-user
/// Bayesian offset that personalises their RDS over time, so the score stops
/// relying on the flat onboarding guess and converges on their real home.
class CheckinScreen extends StatefulWidget {
  const CheckinScreen({
    super.key,
    required this.apiClient,
    required this.userId,
  });

  final PranaApiClient apiClient;
  final String userId;

  @override
  State<CheckinScreen> createState() => _CheckinScreenState();
}

class _CheckinScreenState extends State<CheckinScreen> {
  bool _submitting = false;
  String? _statusMessage;
  bool _done = false;

  Future<void> _submit(String quality) async {
    setState(() {
      _submitting = true;
      _statusMessage = null;
    });

    try {
      final total = await widget.apiClient.recordCheckin(
        userId: widget.userId,
        sleepQuality: quality,
      );
      setState(() {
        _done = true;
        _statusMessage =
            'Thanks - recorded. PRANA now has $total check-in(s) to personalise '
            'your recovery score.';
      });
    } catch (error) {
      setState(() => _statusMessage = error.toString());
    } finally {
      setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Sleep check-in')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'How did you sleep last night?',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 8),
              Text(
                'Your honest answer helps PRANA learn how hot your room actually '
                'gets, so your recovery alerts get more accurate over time.',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              const SizedBox(height: 24),
              _SleepOption(
                emoji: '😴',
                label: 'Slept well',
                description: 'Comfortable - cool enough to rest',
                color: Colors.green,
                enabled: !_submitting && !_done,
                onTap: () => _submit('good'),
              ),
              const SizedBox(height: 12),
              _SleepOption(
                emoji: '😐',
                label: 'A bit warm',
                description: 'Manageable, but not ideal',
                color: Colors.orange,
                enabled: !_submitting && !_done,
                onTap: () => _submit('moderate'),
              ),
              const SizedBox(height: 12),
              _SleepOption(
                emoji: '🥵',
                label: 'Too hot to sleep',
                description: 'Kept waking up - hard to recover',
                color: Colors.red,
                enabled: !_submitting && !_done,
                onTap: () => _submit('poor'),
              ),
              const SizedBox(height: 24),
              if (_submitting)
                const Center(child: CircularProgressIndicator()),
              if (_statusMessage != null) ...[
                Text(
                  _statusMessage!,
                  style: TextStyle(
                    color: _done
                        ? Theme.of(context).colorScheme.primary
                        : Theme.of(context).colorScheme.error,
                  ),
                ),
                const SizedBox(height: 16),
              ],
              if (_done)
                FilledButton(
                  onPressed: () => Navigator.of(context).pop(true),
                  child: const Text('Back to dashboard'),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SleepOption extends StatelessWidget {
  const _SleepOption({
    required this.emoji,
    required this.label,
    required this.description,
    required this.color,
    required this.enabled,
    required this.onTap,
  });

  final String emoji;
  final String label;
  final String description;
  final Color color;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: color.withValues(alpha: 0.08),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: enabled ? onTap : null,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Text(emoji, style: const TextStyle(fontSize: 32)),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      label,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      description,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: color),
            ],
          ),
        ),
      ),
    );
  }
}
