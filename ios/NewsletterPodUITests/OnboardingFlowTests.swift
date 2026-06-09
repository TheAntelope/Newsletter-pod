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
        // The wizard mirrors the Flutter flow. With the seeded two-host profile and
        // the default greeting toggle on, both conditional steps (co-host + name)
        // appear, giving the full 12-step path.

        // Step 1 of 12 — Welcome
        let welcome = app.staticTexts["Welcome to ClawCast."]
        XCTAssertTrue(
            welcome.waitForExistence(timeout: 8),
            "Onboarding welcome screen did not appear"
        )
        attach("01-welcome")
        tapPrimary(label: "Set up my podcast")

        // Step 2 of 12 — Pick your voice (catalog is unseeded, so the picker falls
        // back to the static voice list and pre-selects a host → Continue enabled)
        assertStep("Pick your voice", screenshot: "02-pick-voice")
        tapPrimary(label: "Continue")

        // Step 3 of 12 — Style your show
        assertStep("Style your show", screenshot: "03-style")
        tapPrimary(label: "Continue")

        // Step 4 of 12 — Choose a format (two_hosts is the default selection)
        assertStep("Choose a format", screenshot: "04-show-shape")
        tapPrimary(label: "Continue")

        // Step 5 of 12 — Add a co-host (shown because two_hosts is selected)
        assertStep("Add a co-host", screenshot: "05-co-host")
        tapPrimary(label: "Continue")

        // Step 6 of 12 — What should we call you? (shown because greeting is on)
        assertStep("What should we call you?", screenshot: "06-name")
        tapPrimary(label: "Continue")

        // Step 7 of 12 — Pick your topics
        assertStep("Pick your topics", screenshot: "07-topics")
        tapPrimary(label: "Continue")

        // Step 8 of 12 — Tune your pod (swipe deck loads empty with no backend)
        assertStep("Tune your pod", screenshot: "08-swipe")
        tapPrimary(label: "Continue")

        // Step 9 of 12 — Newsletters (search + voice + paste)
        assertStep("What newsletters do you read?", screenshot: "09-newsletters")
        tapPrimary(label: "Continue")

        // Step 10 of 12 — Add from anywhere (share-sheet teach)
        assertStep("Add from anywhere", screenshot: "10-share")
        tapPrimary(label: "Continue")

        // Step 11 of 12 — Schedule. Tapping Continue persists the profile, name,
        // and schedule (best-effort network) before advancing, so allow extra time.
        assertStep("When should it land?", screenshot: "11-schedule")
        tapPrimary(label: "Continue")

        // Step 12 of 12 — You're all set + first-episode generation kickoff
        assertStep("You're all set", screenshot: "12-done", timeout: 20)
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

    /// Wait for a step's title to appear, then capture a screenshot.
    private func assertStep(_ title: String, screenshot: String, timeout: TimeInterval = 8) {
        XCTAssertTrue(
            app.staticTexts[title].waitForExistence(timeout: timeout),
            "Step '\(title)' did not appear"
        )
        attach(screenshot)
    }

    private func attach(_ name: String) {
        let screenshot = app.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
