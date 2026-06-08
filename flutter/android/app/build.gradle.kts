import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
    // Firebase: applied after the Android + Flutter plugins. Processes
    // app/google-services.json so Firebase.initializeApp() needs no options.
    id("com.google.gms.google-services")
}

// Release signing: CI writes flutter/android/key.properties from the upload
// keystore (see codemagic.yaml). When the file is absent (local dev) we fall
// back to debug signing so `flutter run --release` still works.
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        load(FileInputStream(keystorePropertiesFile))
    }
}

android {
    namespace = "com.newsletterpod.app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        // Required by flutter_local_notifications (uses java.time APIs that
        // need desugaring to run on minSdk 23). Paired with the
        // coreLibraryDesugaring dependency below.
        isCoreLibraryDesugaringEnabled = true
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.newsletterpod.app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        // Firebase Auth requires API 23+. maxOf avoids downgrading if Flutter's
        // default is already higher.
        minSdk = maxOf(23, flutter.minSdkVersion)
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        create("release") {
            if (keystorePropertiesFile.exists()) {
                // as? + error() gives a clear message if key.properties is
                // partially written, rather than a cryptic ClassCastException.
                keyAlias = (keystoreProperties["keyAlias"] as? String)
                    ?: error("keyAlias missing in key.properties")
                keyPassword = (keystoreProperties["keyPassword"] as? String)
                    ?: error("keyPassword missing in key.properties")
                storeFile = file(
                    (keystoreProperties["storeFile"] as? String)
                        ?: error("storeFile missing in key.properties")
                )
                storePassword = (keystoreProperties["storePassword"] as? String)
                    ?: error("storePassword missing in key.properties")
            }
        }
    }

    buildTypes {
        release {
            // Real upload key in CI (key.properties present); debug key locally
            // so `flutter run --release` keeps working without the keystore.
            signingConfig =
                if (keystorePropertiesFile.exists())
                    signingConfigs.getByName("release")
                else
                    signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

dependencies {
    // Backs isCoreLibraryDesugaringEnabled above (required by
    // flutter_local_notifications). 2.1.x is the version range AGP 8 expects.
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")
}
