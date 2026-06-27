import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';

import '../services/api_client.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key, required this.apiClient});

  final PranaApiClient apiClient;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final _locationController = TextEditingController(text: 'Current location');
  final _latController = TextEditingController(text: '13.0827');
  final _lonController = TextEditingController(text: '80.2707');
  final _heatOffsetController = TextEditingController(text: '3.0');
  final List<Map<String, dynamic>> _pastResults = [];

  Map<String, dynamic>? _currentResult;
  String? _statusMessage;
  bool _loadingLocation = false;
  bool _loadingRisk = false;

  @override
  void dispose() {
    _locationController.dispose();
    _latController.dispose();
    _lonController.dispose();
    _heatOffsetController.dispose();
    super.dispose();
  }

  Future<void> _useCurrentLocation() async {
    setState(() {
      _loadingLocation = true;
      _statusMessage = null;
    });

    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        throw Exception('Location services are disabled.');
      }

      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        throw Exception('Location permission was not granted.');
      }

      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
        ),
      );

      setState(() {
        _latController.text = position.latitude.toStringAsFixed(6);
        _lonController.text = position.longitude.toStringAsFixed(6);
        _statusMessage = 'Location detected. Adjust the values if needed.';
      });
    } catch (error) {
      setState(() => _statusMessage = error.toString());
    } finally {
      setState(() => _loadingLocation = false);
    }
  }

  Future<void> _calculateRisk() async {
    final lat = double.tryParse(_latController.text.trim());
    final lon = double.tryParse(_lonController.text.trim());
    final heatOffset = double.tryParse(_heatOffsetController.text.trim());

    if (lat == null || lon == null || heatOffset == null) {
      setState(
        () => _statusMessage = 'Enter valid latitude, longitude, and heat offset.',
      );
      return;
    }

    setState(() {
      _loadingRisk = true;
      _statusMessage = null;
    });

    try {
      final result = await widget.apiClient.getCurrentRisk(
        lat: lat,
        lon: lon,
        locationName: _locationController.text.trim(),
        urbanHeatOffset: heatOffset,
      );

      setState(() {
        _currentResult = result;
        _pastResults.insert(0, result);
        _statusMessage = 'Risk updated from backend.';
      });
    } catch (error) {
      setState(() => _statusMessage = error.toString());
    } finally {
      setState(() => _loadingRisk = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('PRANA'),
        actions: [
          IconButton(
            onPressed: _loadingRisk ? null : _calculateRisk,
            tooltip: 'Refresh risk',
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _LocationPanel(
              locationController: _locationController,
              latController: _latController,
              lonController: _lonController,
              heatOffsetController: _heatOffsetController,
              loadingLocation: _loadingLocation,
              loadingRisk: _loadingRisk,
              onUseCurrentLocation: _useCurrentLocation,
              onCalculateRisk: _calculateRisk,
            ),
            if (_statusMessage != null) ...[
              const SizedBox(height: 12),
              Text(
                _statusMessage!,
                style: TextStyle(color: Theme.of(context).colorScheme.primary),
              ),
            ],
            const SizedBox(height: 16),
            _CurrentRiskPanel(result: _currentResult),
            const SizedBox(height: 16),
            _PastResultsPanel(results: _pastResults),
          ],
        ),
      ),
    );
  }
}

class _LocationPanel extends StatelessWidget {
  const _LocationPanel({
    required this.locationController,
    required this.latController,
    required this.lonController,
    required this.heatOffsetController,
    required this.loadingLocation,
    required this.loadingRisk,
    required this.onUseCurrentLocation,
    required this.onCalculateRisk,
  });

  final TextEditingController locationController;
  final TextEditingController latController;
  final TextEditingController lonController;
  final TextEditingController heatOffsetController;
  final bool loadingLocation;
  final bool loadingRisk;
  final VoidCallback onUseCurrentLocation;
  final VoidCallback onCalculateRisk;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Location', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            TextField(
              controller: locationController,
              decoration: const InputDecoration(labelText: 'Location name'),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: latController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'Latitude'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: TextField(
                    controller: lonController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'Longitude'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            TextField(
              controller: heatOffsetController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Urban heat offset C',
              ),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                FilledButton.icon(
                  onPressed: loadingLocation ? null : onUseCurrentLocation,
                  icon:
                      loadingLocation
                          ? const SizedBox.square(
                            dimension: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                          : const Icon(Icons.my_location),
                  label: const Text('Use GPS'),
                ),
                FilledButton.icon(
                  onPressed: loadingRisk ? null : onCalculateRisk,
                  icon:
                      loadingRisk
                          ? const SizedBox.square(
                            dimension: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                          : const Icon(Icons.insights),
                  label: const Text('Calculate'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _CurrentRiskPanel extends StatelessWidget {
  const _CurrentRiskPanel({required this.result});

  final Map<String, dynamic>? result;

  @override
  Widget build(BuildContext context) {
    if (result == null) {
      return const Card(
        child: Padding(
          padding: EdgeInsets.all(18),
          child: Text('Live PRANA results will appear here.'),
        ),
      );
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Live Results', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                _MetricTile(label: 'CCRI', value: _format(result!['ccri'])),
                _MetricTile(
                  label: 'NDT',
                  value: '${_format(result!['ndt'])} C',
                ),
                _MetricTile(label: 'HA-AQI', value: _format(result!['ha_aqi'])),
                _MetricTile(label: 'RDS', value: _format(result!['rds'])),
              ],
            ),
            const SizedBox(height: 12),
            Text('Risk: ${result!['risk_level'] ?? 'Unknown'}'),
            const SizedBox(height: 8),
            Text(result!['alert_message']?.toString() ?? ''),
          ],
        ),
      ),
    );
  }
}

class _PastResultsPanel extends StatelessWidget {
  const _PastResultsPanel({required this.results});

  final List<Map<String, dynamic>> results;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Past Results', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            if (results.isEmpty)
              const Text('No past results in this session.')
            else
              for (final result in results.take(5))
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text('${result['location']}'),
                  subtitle: Text('${result['timestamp']}'),
                  trailing: Text('CCRI ${_format(result['ccri'])}'),
                ),
          ],
        ),
      ),
    );
  }
}

class _MetricTile extends StatelessWidget {
  const _MetricTile({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 145,
      child: DecoratedBox(
        decoration: BoxDecoration(
          border: Border.all(
            color: Theme.of(context).colorScheme.outlineVariant,
          ),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: Theme.of(context).textTheme.labelMedium),
              const SizedBox(height: 4),
              Text(value, style: Theme.of(context).textTheme.titleLarge),
            ],
          ),
        ),
      ),
    );
  }
}

String _format(Object? value) {
  if (value == null) {
    return 'N/A';
  }
  if (value is num) {
    return value.toStringAsFixed(1);
  }
  return value.toString();
}
