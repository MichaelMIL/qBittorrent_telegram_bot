import 'dart:async';

import 'package:flutter/material.dart';
import 'package:qbit_web/api/client.dart';
import 'package:qbit_web/format.dart';
import 'package:qbit_web/models.dart';
import 'package:qbit_web/state.dart';
import 'package:qbit_web/widgets/common.dart';

/// Disk health and storage usage of the QNAP, as reported by the agent that
/// runs next to it (agent/qnap_agent.py). Polls every minute.
class NasScreen extends StatefulWidget {
  const NasScreen({super.key});

  @override
  State<NasScreen> createState() => _NasScreenState();
}

class _NasScreenState extends State<NasScreen> {
  NasView? _view;
  String? _error;
  Timer? _timer;
  bool _refreshing = false; // asked the agent, waiting for its report

  @override
  void initState() {
    super.initState();
    unawaited(_load());
    _schedule(60);
  }

  /// (Re)arm the auto-reload with the period the server configured.
  void _schedule(int seconds) {
    if (_timer != null && _timer!.isActive && _period == seconds) return;
    _timer?.cancel();
    _period = seconds;
    _timer = Timer.periodic(
      Duration(seconds: seconds),
      (_) => unawaited(_load(silent: true)),
    );
  }

  int _period = 60;

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    try {
      final data = await AppScope.read(context).api.get('/api/nas');
      if (!mounted) return;
      setState(() {
        _view = NasView.fromJson(data);
        _error = null;
      });
      _schedule(_view!.pageReloadSeconds);
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.unauthorized) unawaited(AppScope.read(context).connect());
      if (!silent || _view == null) setState(() => _error = e.message);
    }
  }

  /// Ask the agent(s) for a fresh report and wait for it to arrive.
  Future<void> _refreshNow() async {
    final state = AppScope.read(context);
    final before = {
      for (final a in _view?.agents ?? <NasAgent>[]) a.name: a.receivedAt,
    };
    setState(() => _refreshing = true);
    final ok = await guard(context, () => state.api.post('/api/nas/refresh'));
    if (ok == null) {
      if (mounted) setState(() => _refreshing = false);
      return;
    }
    // the agent checks in every few seconds; wait as long as the server says
    final poll = _view?.refreshPollSeconds ?? 2;
    final rounds = ((_view?.refreshTimeoutSeconds ?? 45) / poll).ceil();
    var fresh = false;
    for (var i = 0; i < rounds && mounted; i++) {
      await Future<void>.delayed(Duration(seconds: poll));
      await _load(silent: true);
      final agents = _view?.agents ?? const <NasAgent>[];
      fresh = agents.any((a) => a.receivedAt != before[a.name]);
      if (fresh) break;
    }
    if (!mounted) return;
    setState(() => _refreshing = false);
    showSnack(
      context,
      fresh
          ? '✅ Fresh report received.'
          : "⏳ The agent hasn't answered yet — is it running? The request "
                'stays queued; the page updates when the report lands.',
    );
  }

  @override
  Widget build(BuildContext context) {
    final view = _view;
    final hasAgents = view != null && view.agents.isNotEmpty;
    return Scaffold(
      appBar: AppBar(
        title: const Text('🗄 NAS'),
        actions: [
          if (hasAgents)
            TextButton.icon(
              onPressed: _refreshing ? null : _refreshNow,
              icon: _refreshing
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.sync, size: 18),
              label: Text(_refreshing ? 'Waiting for agent…' : 'Refresh now'),
            ),
          IconButton(
            tooltip: 'Reload',
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
      ),
      body: view == null
          ? (_error != null
                ? EmptyView(
                    icon: Icons.error_outline,
                    text: _error!,
                    onRetry: _load,
                  )
                : const Center(child: CircularProgressIndicator()))
          : view.agents.isEmpty
          ? EmptyView(
              icon: Icons.storage_outlined,
              text: view.configured
                  ? 'No report yet. Start agent/qnap_agent.py on the machine '
                        'next to the NAS; it reports every few minutes.'
                  : "Agents are off. Set AGENT_TOKEN in the server's .env and "
                        'run agent/qnap_agent.py next to the NAS.',
              onRetry: _load,
              retryLabel: 'Reload',
            )
          : RefreshIndicator(
              onRefresh: _load,
              child: Constrained(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(12, 8, 12, 32),
                  children: [
                    for (final a in view.agents)
                      _AgentCard(agent: a, thresholds: view),
                  ],
                ),
              ),
            ),
    );
  }
}

class _AgentCard extends StatelessWidget {
  const _AgentCard({required this.agent, required this.thresholds});
  final NasAgent agent;
  final NasView thresholds;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final r = agent.report;
    final sys = r.system;
    final statusColor = !agent.online
        ? theme.colorScheme.error
        : agent.alerts.isEmpty
        ? Colors.green
        : Colors.orange;
    final statusText = !agent.online
        ? 'offline — last report ${agent.receivedAt == null ? 'never' : fmtAgo(agent.receivedAt!)}'
        : agent.alerts.isEmpty
        ? 'healthy · reported ${fmtAgo(agent.receivedAt!)}'
        : '${agent.alerts.length} alert${agent.alerts.length == 1 ? '' : 's'} · reported ${fmtAgo(agent.receivedAt!)}';
    final pending = agent.refreshPending ? ' · refresh requested' : '';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Card(
          child: ListTile(
            leading: Icon(Icons.circle, color: statusColor, size: 16),
            title: Text(
              [
                if (sys.name.isNotEmpty) sys.name else agent.name,
                if (sys.model.isNotEmpty) sys.model,
              ].join(' · '),
              style: theme.textTheme.titleMedium,
            ),
            subtitle: Text('$statusText$pending'),
          ),
        ),
        if (!r.ok)
          Card(
            color: theme.colorScheme.errorContainer,
            child: ListTile(
              leading: const Icon(Icons.error_outline),
              title: const Text("The agent can't read the NAS"),
              subtitle: Text(r.error),
            ),
          ),
        if (r.ok) ...[
          Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: Wrap(
                spacing: 24,
                runSpacing: 8,
                children: [
                  _fact('Health', sys.health.isEmpty ? '—' : sys.health),
                  if (sys.firmware.isNotEmpty) _fact('Firmware', sys.firmware),
                  if (sys.uptimeSeconds > 0)
                    _fact('Uptime', fmtEta(sys.uptimeSeconds)),
                  if (sys.tempC != null) _fact('System', '${sys.tempC} °C'),
                  if (sys.cpuTempC != null) _fact('CPU', '${sys.cpuTempC} °C'),
                  if (sys.cpuPercent != null)
                    _fact('CPU load', '${sys.cpuPercent!.toStringAsFixed(0)}%'),
                  if (sys.memoryTotalMb != null && sys.memoryFreeMb != null)
                    _fact(
                      'Memory',
                      '${((sys.memoryTotalMb! - sys.memoryFreeMb!) / 1024).toStringAsFixed(1)} / '
                          '${(sys.memoryTotalMb! / 1024).toStringAsFixed(1)} GiB',
                    ),
                ],
              ),
            ),
          ),
          SectionTitle('💽 Disks (${r.disks.length})'),
          for (final d in r.disks)
            ListTile(
              leading: Text(
                d.type == 'ssd' ? '🟦' : '💿',
                style: const TextStyle(fontSize: 22),
              ),
              title: Text('Slot ${d.slot} · ${d.model}'),
              subtitle: Text(
                [
                  if (d.capacity.isNotEmpty) d.capacity,
                  if (d.serial.isNotEmpty) 'S/N ${d.serial}',
                ].join(' · '),
              ),
              trailing: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  _HealthChip(d.health),
                  if (d.tempC != null)
                    Text(
                      '${d.tempC} °C',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: d.tempC! >= thresholds.diskTempC
                            ? theme.colorScheme.error
                            : null,
                        fontWeight: d.tempC! >= thresholds.diskTempC
                            ? FontWeight.bold
                            : null,
                      ),
                    ),
                ],
              ),
            ),
          SectionTitle('📦 Volumes (${r.volumes.length})'),
          for (final v in r.volumes)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          v.label,
                          style: theme.textTheme.titleSmall,
                        ),
                      ),
                      _HealthChip(v.status),
                    ],
                  ),
                  const SizedBox(height: 6),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: LinearProgressIndicator(
                      value: (v.usedPercent ?? 0) / 100,
                      minHeight: 10,
                      color: (v.usedPercent ?? 0) >= thresholds.usagePercent
                          ? theme.colorScheme.error
                          : null,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    v.usedPercent == null
                        ? 'usage unknown'
                        : '${v.usedPercent!.toStringAsFixed(1)}% used · '
                              '${fmtSize(v.totalBytes - v.freeBytes)} of '
                              '${fmtSize(v.totalBytes)} · ${fmtSize(v.freeBytes)} free',
                    style: theme.textTheme.bodySmall,
                  ),
                  if (v.folders.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        [
                          for (final f in v.folders.take(6))
                            '${f.name} ${fmtSize(f.usedBytes)}',
                        ].join(' · '),
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                ],
              ),
            ),
        ],
        if (agent.alerts.isNotEmpty) ...[
          const SectionTitle('🚨 Active alerts'),
          for (final a in agent.alerts)
            ListTile(
              dense: true,
              leading: const Icon(Icons.warning_amber, color: Colors.orange),
              title: Text(a.replaceAll(':', ' ')),
            ),
        ],
        const SizedBox(height: 12),
      ],
    );
  }

  Widget _fact(String k, String v) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(k, style: const TextStyle(fontSize: 11)),
      Text(v, style: const TextStyle(fontWeight: FontWeight.w600)),
    ],
  );
}

/// Green for good/ready, orange otherwise.
class _HealthChip extends StatelessWidget {
  const _HealthChip(this.value);
  final String value;

  @override
  Widget build(BuildContext context) {
    final good = const {
      'good',
      'ok',
      'normal',
      'healthy',
      'ready',
    }.contains(value.toLowerCase());
    final color = value.isEmpty
        ? Theme.of(context).colorScheme.outline
        : good
        ? Colors.green
        : Colors.orange;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color),
      ),
      child: Text(
        value.isEmpty ? 'unknown' : value,
        style: TextStyle(color: color, fontSize: 12),
      ),
    );
  }
}
