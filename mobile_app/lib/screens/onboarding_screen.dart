// mobile_app/lib/screens/onboarding_screen.dart

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/user_registration.dart';
import '../services/api_client.dart';

class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({
    super.key,
    required this.apiClient,
    required this.onContinue,
  });

  final PranaApiClient apiClient;

  /// Called when the user proceeds to the dashboard. Passes the home profile
  /// and, when registration completed, the user id so the dashboard can
  /// request personalised RDS and record sleep check-ins.
  final void Function(HomeProfile profile, String? userId) onContinue;

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _phoneController = TextEditingController();
  final _locationNameController = TextEditingController(text: 'Current location');
  final _latController = TextEditingController();
  final _lonController = TextEditingController();

  bool _ac = false;
  bool _fan = false;
  bool _windowsOpen = false;
  int _occupants = 1;
  String _roofMaterial = 'concrete';
  String _floorLevel = 'ground';

  bool _loadingLocation = false;
  bool _registering = false;
  String? _statusMessage;
  RegisterResult? _result;

  @override
  void dispose() {
    _phoneController.dispose();
    _locationNameController.dispose();
    _latController.dispose();
    _lonController.dispose();
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
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.high),
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

  HomeProfile _buildProfile() => HomeProfile(
        ac: _ac,
        roofMaterial: _roofMaterial,
        floorLevel: _floorLevel,
        fan: _fan,
        windowsOpen: _windowsOpen,
        occupants: _occupants,
      );

  Future<void> _register() async {
    final phone = _phoneController.text.trim();
    final lat = double.tryParse(_latController.text.trim());
    final lon = double.tryParse(_lonController.text.trim());

    if (phone.isEmpty || lat == null || lon == null) {
      setState(() => _statusMessage = 'Enter phone, latitude, and longitude.');
      return;
    }

    setState(() {
      _registering = true;
      _statusMessage = null;
    });

    try {
      final result = await widget.apiClient.register(
        RegistrationRequest(
          phone: phone,
          locationName: _locationNameController.text.trim(),
          lat: lat,
          lon: lon,
          urbanHeatOffset: null,
          onboarding: _buildProfile(),
        ),
      );
      setState(() {
        _result = result;
        _statusMessage = 'Registered. Activate WhatsApp alerts below.';
      });
    } catch (error) {
      setState(() => _statusMessage = error.toString());
    } finally {
      setState(() => _registering = false);
    }
  }

  Future<void> _openWhatsApp() async {
    if (_result == null) return;
    final uri = Uri.parse(_result!.whatsappLink);
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('PRANA — Set up alerts')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      TextField(
                        key: const Key('phoneField'),
                        controller: _phoneController,
                        keyboardType: TextInputType.phone,
                        decoration: const InputDecoration(labelText: 'WhatsApp phone number'),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        key: const Key('locationNameField'),
                        controller: _locationNameController,
                        decoration: const InputDecoration(labelText: 'Location name'),
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          Expanded(
                            child: TextField(
                              key: const Key('latField'),
                              controller: _latController,
                              keyboardType: TextInputType.number,
                              decoration: const InputDecoration(labelText: 'Latitude'),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: TextField(
                              key: const Key('lonField'),
                              controller: _lonController,
                              keyboardType: TextInputType.number,
                              decoration: const InputDecoration(labelText: 'Longitude'),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      FilledButton.icon(
                        onPressed: _loadingLocation ? null : _useCurrentLocation,
                        icon: _loadingLocation
                            ? const SizedBox.square(
                                dimension: 16,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.my_location),
                        label: const Text('Use GPS'),
                      ),
                      const SizedBox(height: 16),
                      Text('Home profile', style: Theme.of(context).textTheme.titleMedium),
                      SwitchListTile(
                        key: const Key('acSwitch'),
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Has air conditioning'),
                        value: _ac,
                        onChanged: (v) => setState(() => _ac = v),
                      ),
                      SwitchListTile(
                        key: const Key('fanSwitch'),
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Uses a fan while sleeping'),
                        value: _fan,
                        onChanged: (v) => setState(() => _fan = v),
                      ),
                      SwitchListTile(
                        key: const Key('windowsSwitch'),
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Keeps windows open at night'),
                        value: _windowsOpen,
                        onChanged: (v) => setState(() => _windowsOpen = v),
                      ),
                      DropdownButtonFormField<String>(
                        key: const Key('roofDropdown'),
                        value: _roofMaterial,
                        decoration: const InputDecoration(labelText: 'Roof material'),
                        items: const [
                          DropdownMenuItem(value: 'concrete', child: Text('Concrete')),
                          DropdownMenuItem(value: 'tin', child: Text('Tin')),
                          DropdownMenuItem(value: 'other', child: Text('Other')),
                        ],
                        onChanged: (v) => setState(() => _roofMaterial = v ?? 'concrete'),
                      ),
                      const SizedBox(height: 10),
                      DropdownButtonFormField<String>(
                        key: const Key('floorDropdown'),
                        value: _floorLevel,
                        decoration: const InputDecoration(labelText: 'Floor level'),
                        items: const [
                          DropdownMenuItem(value: 'ground', child: Text('Ground')),
                          DropdownMenuItem(value: 'middle', child: Text('Middle')),
                          DropdownMenuItem(value: 'top', child: Text('Top')),
                        ],
                        onChanged: (v) => setState(() => _floorLevel = v ?? 'ground'),
                      ),
                      const SizedBox(height: 10),
                      DropdownButtonFormField<int>(
                        key: const Key('occupantsDropdown'),
                        value: _occupants,
                        decoration: const InputDecoration(
                          labelText: 'People sleeping in the room',
                        ),
                        items: const [
                          DropdownMenuItem(value: 1, child: Text('1')),
                          DropdownMenuItem(value: 2, child: Text('2')),
                          DropdownMenuItem(value: 3, child: Text('3')),
                          DropdownMenuItem(value: 4, child: Text('4 or more')),
                        ],
                        onChanged: (v) => setState(() => _occupants = v ?? 1),
                      ),
                      const SizedBox(height: 16),
                      FilledButton(
                        key: const Key('registerButton'),
                        onPressed: _registering ? null : _register,
                        child: _registering
                            ? const SizedBox.square(
                                dimension: 16,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Text('Register'),
                      ),
                    ],
                  ),
                ),
              ),
              if (_statusMessage != null) ...[
                const SizedBox(height: 12),
                Text(
                  _statusMessage!,
                  style: TextStyle(color: Theme.of(context).colorScheme.primary),
                ),
              ],
              if (_result != null) ...[
                const SizedBox(height: 16),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Two more steps to activate WhatsApp alerts'),
                        const SizedBox(height: 8),
                        Text(
                          "1. Send \"join ${_result!.sandboxJoinCode}\" to PRANA's "
                          'WhatsApp number',
                        ),
                        const SizedBox(height: 4),
                        const Text('2. Then tap below to finish activation'),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 10,
                          children: [
                            FilledButton(
                              onPressed: _openWhatsApp,
                              child: const Text('Open WhatsApp'),
                            ),
                            OutlinedButton(
                              onPressed: () =>
                                  widget.onContinue(_buildProfile(), _result?.userId),
                              child: const Text('Continue to Dashboard'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
