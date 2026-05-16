import XCTest

/// End-to-end UI tests that walk through the new-user onboarding wizard and
/// capture a screenshot at each step.
///
/// To run on a Mac:
///
///   cd ios
///   xcodegen generate --spec project.yml
///   xcodebuild test \
///     -project NewsletterPod.xcodeproj \
///     -scheme NewsletterPod \
///     -destination 'platform=iOS Simulator,name=iPhone 15,OS=latest' \
///     -resultBundlePath build/onboarding.xcresult
///
/// Screenshots land in the .xcresult bundle (open it in Xcode or extract via
/// `xcrun xcresulttool get --path build/onboarding.xcresult --format json`).
///
/// The app launches with the `-uiTestMode` argument, which seeds AppViewModel
/// with a fake session and a "Listener" user so the wizard appears immediately
/// without hitting the real backend or going through Sign In with Apple.
/// Network-backed save calls inside the wizard will fail silently, but the UI
/// still advances between steps because the wizard advances optimistically.
final class OnboardingFlowTests: XCTestCase {
    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments += ["-uiTestMode"]
        app.launch()
    }

    func testOnboardingHappyPath() throws {
        // Step 1 of 8 — Welcome
        let welcome = app.staticTexts["Welcome to ClawCast."]
        XCTAssertTrue(
            welcome.waitForExistence(timeout: 8),
            "Onboarding welcome screen did not appear"
        )
        attach("01-welcome")

        tapPrimary(label: "Set up my podcast")

        // Step 2 of 8 — Voice intake (skippable; simulator can't dictate)
        XCTAssertTrue(
            app.staticTexts["Tell me what's on your mind."].waitForExistence(timeout: 5),
            "Voice intake step did not appear"
        )
        attach("02-voice-intake")
        tapSkipInStep(matching: "Skip — let the system learn from swipes")

        // Step 3 of 8 — Swipe deck (no real backend, so deck loads empty and
        // primary Continue is enabled immediately)
        XCTAssertTrue(
            app.staticTexts["What grabs you?"].waitForExistence(timeout: 5),
            "Swipe deck step did not appear"
        )
        attach("03-swipe-deck")
        tapPrimary(label: "Continue")

        // Step 4 of 8 — Newsletters (optional paste)
        XCTAssertTrue(
            app.staticTexts["Any Substacks you already read?"].waitForExistence(timeout: 5),
            "Newsletters step did not appear"
        )
        attach("04-newsletters")
        tapPrimary(label: "Continue")

        // Step 5 of 8 — Show shape
        waitForAnyContinue()
        attach("05-show-shape")
        tapPrimary(label: "Continue")

        // Step 6 of 8 — Voices (two_hosts preset is the default → shown)
        waitForAnyContinue()
        attach("06-voices")
        tapPrimary(label: "Continue")

        // Step 7 of 8 — Schedule
        waitForAnyContinue()
        attach("07-schedule")
        tapPrimary(label: "Continue")

        // Step 8 of 8 — Alias card + first-episode generation kickoff
        Thread.sleep(forTimeInterval: 1.5)
        attach("08-alias")
    }

    func testWelcomeGreetingDropsEmailPrefixUser() throws {
        // The seeded user has displayName="Listener", which UserDTO.hasFriendlyName
        // treats as no friendly name. The welcome screen should fall back to
        // "Welcome to ClawCast." instead of "Hi <junk-name> — welcome to ClawCast."
        let welcome = app.staticTexts["Welcome to ClawCast."]
        XCTAssertTrue(
            welcome.waitForExistence(timeout: 8),
            "Expected anonymous welcome line, got: \(app.debugDescription)"
        )
        XCTAssertFalse(
            app.staticTexts.containing(NSPredicate(format: "label CONTAINS 'Listener'")).element.exists,
            "Greeting leaked the 'Listener' sentinel"
        )
        attach("welcome-anon")
    }

    // MARK: - helpers

    private func tapPrimary(label: String) {
        let button = app.buttons[label].firstMatch
        if button.waitForExistence(timeout: 5) {
            button.tap()
        } else {
            XCTFail("Button '\(label)' never appeared")
        }
    }

    private func tapSkipInStep(matching label: String) {
        // The optional skip buttons inside voice intake / newsletters use long,
        // copy-driven labels. Match by prefix in case the copy shifts.
        let predicate = NSPredicate(format: "label BEGINSWITH %@", String(label.prefix(20)))
        let button = app.buttons.matching(predicate).firstMatch
        if button.waitForExistence(timeout: 5) {
            button.tap()
        } else {
            XCTFail("Skip button matching '\(label)' never appeared")
        }
    }

    private func waitForAnyContinue() {
        let anyContinue = app.buttons["Continue"].firstMatch
        _ = anyContinue.waitForExistence(timeout: 5)
    }

    private func attach(_ name: String) {
        let screenshot = app.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
