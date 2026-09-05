import 'package:flutter/material.dart';

import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/state.dart';

/// Server URL + password. Normally the app is served by the backend itself,
/// so the URL is pre-filled; only `flutter run` dev builds need to change it.
class ConnectScreen extends StatefulWidget {
  const ConnectScreen({super.key});

  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends State<ConnectScreen> {
  late final TextEditingController _url = TextEditingController(
    text: AppScope.read(context).api.baseUrl,
  );
  final _password = TextEditingController();
  bool _busy = false;
  String? _error;

  Future<void> _submit() async {
    final state = AppScope.read(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final ok = await state.connect(baseUrl: _url.text);
      if (!ok && state.connectError != null && !state.authRequired) {
        setState(() => _error = state.connectError);
        return;
      }
      if (!ok && state.authRequired) {
        if (_password.text.isEmpty) {
          setState(
            () => _error = 'This server needs the password (WEB_PASSWORD).',
          );
          return;
        }
        await state.login(_password.text);
      }
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Image(
                      image: AssetImage('assets/logo.png'),
                      width: 96,
                      height: 96,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Torrent butler',
                      style: Theme.of(context).textTheme.headlineSmall,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'qBittorrent · HeBits · Plex',
                      style: Theme.of(context).textTheme.bodyMedium,
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 24),
                    TextField(
                      controller: _url,
                      keyboardType: TextInputType.url,
                      decoration: const InputDecoration(
                        labelText: 'Server',
                        hintText: 'http://192.168.1.50:8765',
                        prefixIcon: Icon(Icons.dns_outlined),
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _password,
                      obscureText: true,
                      autofocus: state.authRequired,
                      onSubmitted: (_) => _submit(),
                      decoration: InputDecoration(
                        labelText: 'Password',
                        helperText: state.authRequired
                            ? 'Admin or user password (ADMIN_PASSWORD / '
                                  "USER_PASSWORD in the server's .env)"
                            : 'Leave empty if the server has no ADMIN_PASSWORD',
                        prefixIcon: const Icon(Icons.lock_outline),
                        border: const OutlineInputBorder(),
                      ),
                    ),
                    if (_error != null || state.connectError != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        _error ?? state.connectError!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ],
                    const SizedBox(height: 20),
                    FilledButton.icon(
                      onPressed: _busy ? null : _submit,
                      icon: _busy
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.login),
                      label: const Text('Connect'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
