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
        // Step 1 of 5 — Welcome
        let welcome = app.staticTexts["Welcome to ClawCast."]
        XCTAssertTrue(
            welcome.waitForExistence(timeout: 8),
            "Onboarding welcome screen did not appear"
        )
        attach("01-welcome")

        tapPrimary(label: "Let's set it up")

        // Step 2 of 5 — Pick a starter pack
        XCTAssertTrue(
            app.staticTexts["Pick a starter pack."].waitForExistence(timeout: 5),
            "Sources step did not appear"
        )
        attach("02-sources")
        tapPrimary(label: "Continue")

        // Step 3 of 5 — Show shape
        // The label varies across copy iterations; just wait for any Continue.
        waitForAnyContinue()
        attach("03-show-shape")
        tapPrimary(label: "Continue")

        // Step 4 of 5 — Schedule
        waitForAnyContinue()
        attach("04-schedule")
        tapPrimary(label: "Continue")

        // Step 5 of 5 — Done
        // Allow up to 10s for the optional auto-generate kickoff to settle.
        Thread.sleep(forTimeInterval: 1.5)
        attach("05-done")
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
