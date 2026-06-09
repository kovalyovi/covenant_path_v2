plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.example.covenant_path_viewer"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // Real application id (matches the membercovenantpath.org domain). The Kotlin MainActivity
        // package stays com.example.* — Flutter's activity package is independent of applicationId.
        applicationId = "org.membercovenantpath.viewer"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // Sideload/test builds are signed with the DEBUG key so `flutter build apk` needs no
            // secrets and the APK installs on any device. For a Play Store / production release,
            // add a real keystore signingConfig here (see docs/ANDROID.md) — out of scope for the
            // current test-distribution APK.
            signingConfig = signingConfigs.getByName("debug")
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
