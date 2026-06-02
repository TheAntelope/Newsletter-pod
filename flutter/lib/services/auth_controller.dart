import 'package:firebase_auth/firebase_auth.dart';
import 'package:google_sign_in/google_sign_in.dart';

import '../config.dart';

/// Thrown when the user cancels the Google account picker (so the caller can
/// quietly stand down rather than surface an error).
class SignInCancelled implements Exception {
  const SignInCancelled();
}

/// Result of a successful Google→Firebase sign-in: the **Firebase** ID token
/// (the thing the backend's FirebaseIdentityVerifier validates) plus the
/// display name to seed the new-user profile.
typedef FirebaseSignIn = ({String idToken, String? displayName});

/// Wraps the Google account picker + Firebase credential exchange.
///
/// Nothing here is constructed or imported's-channels touched until
/// [signInWithGoogle] runs, which only happens on the real (flag-on) path —
/// the demo build and widget tests never reach it.
class AuthController {
  AuthController({GoogleSignIn? googleSignIn, FirebaseAuth? firebaseAuth})
      : _googleSignIn = googleSignIn ??
            GoogleSignIn(
              serverClientId: AppConfig.googleServerClientId,
              scopes: const ['email'],
            ),
        _auth = firebaseAuth ?? FirebaseAuth.instance;

  final GoogleSignIn _googleSignIn;
  final FirebaseAuth _auth;

  /// Runs the Google picker, federates the account through Firebase, and
  /// returns a fresh Firebase ID token. Throws [SignInCancelled] if the user
  /// dismisses the picker.
  Future<FirebaseSignIn> signInWithGoogle() async {
    final account = await _googleSignIn.signIn();
    if (account == null) throw const SignInCancelled();

    final googleAuth = await account.authentication;
    final credential = GoogleAuthProvider.credential(
      idToken: googleAuth.idToken,
      accessToken: googleAuth.accessToken,
    );

    final userCredential = await _auth.signInWithCredential(credential);
    final user = userCredential.user;
    if (user == null) {
      throw FirebaseAuthException(
        code: 'no-user',
        message: 'Firebase returned no user after sign-in.',
      );
    }

    final idToken = await user.getIdToken();
    if (idToken == null || idToken.isEmpty) {
      throw FirebaseAuthException(
        code: 'no-id-token',
        message: 'Firebase returned an empty ID token.',
      );
    }
    return (idToken: idToken, displayName: user.displayName);
  }

  /// Clears both the Firebase session and the cached Google account so the next
  /// sign-in re-shows the picker.
  Future<void> signOut() async {
    await _auth.signOut();
    await _googleSignIn.signOut();
  }
}
