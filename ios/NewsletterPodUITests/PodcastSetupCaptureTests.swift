import XCTest

/// Captures screenshots of the Podcast Setup tab so design changes outside the
/// onboarding wizard (like the 3/4/5-min duration picker and the GPS-backed
/// weather location row) get visual review on every CI build.
///
/// Launches with `-uiTestSkipOnboarding` alongside `-uiTestMode` so the app
/// drops straight onto the dashboard — bypassing the force-reopen wizard
/// behavior that `evaluateOnboardingTrigger` applies in plain `-uiTestMode`.
final class PodcastSetupCaptureTests: XCTestCase {
    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments += ["-uiTestMode", "-uiTestSkipOnboarding"]
        app.launch()
    }

    func testPodcastSetupCapture() throws {
        // Wait for the dashboard's tab bar to settle before touching it.
        let podcastTab = app.tabBars.buttons["Podcast"]
        XCTAssertTrue(
            podcastTab.waitForExistence(timeout: 8),
            "Podcast tab not found on the dashboard"
        )
        podcastTab.tap()

        // SwiftUI navigation bar identifiers and Form section headers are
        // both unreliable across iOS versions; anchor on the seeded
        // "First name" text field instead — XCUITest exposes TextField
        // placeholders consistently.
        let firstNameField = app.textFields["First name"]
        XCTAssertTrue(
            firstNameField.waitForExistence(timeout: 12),
            "Podcast Setup screen did not appear (First name field never showed up)"
        )

        // Top of the form: You / Format / Voice cast.
        attach("setup-01-top")

        // Mid-form: scroll until the Style section's Include weather toggle
        // is on screen — that's where the new GPS-backed location row lives.
        let weatherToggle = app.switches["Include weather"]
        var scrolls = 0
        while !weatherToggle.isHittable, scrolls < 6 {
            app.swipeUp()
            scrolls += 1
        }
        attach("setup-02-style-weather")

        // Bottom of form: scroll further to reveal the Duration circles and
        // the delivery schedule. The "Time" picker is a DatePicker that
        // XCUITest reliably exposes near the bottom of the form.
        scrolls = 0
        while !app.staticTexts["Time"].isHittable, scrolls < 6 {
            app.swipeUp()
            scrolls += 1
        }
        attach("setup-03-duration")
    }

    private func attach(_ name: String) {
        let screenshot = app.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
