import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:just_audio/just_audio.dart';

/// App-wide single-stream audio playback for short clips (voice samples).
///
/// One [AudioPlayer] is shared so starting a new clip stops the previous one;
/// [playingId] drives the "Playing…" state on the cards. The player is created
/// lazily on first [toggle] so widget tests that never hit play don't touch the
/// platform channel.
class AudioController extends ChangeNotifier {
  AudioController._();
  static final AudioController instance = AudioController._();

  AudioPlayer? _player;
  String? _playingId;
  String? get playingId => _playingId;

  bool isPlaying(String id) => _playingId == id;

  AudioPlayer _ensurePlayer() {
    final existing = _player;
    if (existing != null) return existing;
    final player = AudioPlayer();
    player.playerStateStream.listen((state) {
      if (state.processingState == ProcessingState.completed) {
        _playingId = null;
        notifyListeners();
      }
    });
    _player = player;
    return player;
  }

  /// Start [source] for [id], or stop if it's already the one playing. [source]
  /// is a network URL (`http…`) or a bundled asset path (`assets/…`).
  ///
  /// Always stops the current clip before loading a new source: swapping the
  /// source on a player that's still loading/playing the previous one is
  /// unreliable (especially on web — the new `setUrl` gets aborted and the old
  /// element keeps playing), which made every card play whichever sample was
  /// heard first. The `_playingId != id` guard after the await drops a load that
  /// a newer tap has already superseded.
  Future<void> toggle(String id, String source) async {
    final player = _ensurePlayer();
    final wasPlaying = _playingId;
    await player.stop();
    if (wasPlaying == id) {
      // Tapped the one that was already playing → just stop (toggle off).
      _playingId = null;
      notifyListeners();
      return;
    }
    _playingId = id;
    notifyListeners();
    try {
      if (source.startsWith('http')) {
        await player.setUrl(source);
      } else {
        await player.setAsset(source);
      }
      if (_playingId != id) return; // a newer toggle won the race
      unawaited(player.play());
    } catch (_) {
      if (_playingId == id) {
        _playingId = null;
        notifyListeners();
      }
    }
  }

  Future<void> stop() async {
    await _player?.stop();
    _playingId = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _player?.dispose();
    super.dispose();
  }
}
