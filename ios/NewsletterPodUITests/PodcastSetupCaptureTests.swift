import XCTest

/// Captures screenshots of the Podcast Setup tab so design changes outside the
/// onboarding wizard (like the 3/4/5-min duration picker and the GPS-backed
/// weather location row) get visual review on every CI build.
///
/// Skips through onboarding via the welcome step's Skip button rather than
/// walking the full flow — that's covered by `OnboardingFlowTests`.
final class PodcastSetupCaptureTests: XCTestCase {
    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments += ["-uiTestMode"]
        app.launch()
    }

    func testPodcastSetupCapture() throws {
        // Bail out of the wizard immediately to land on the dashboard.
        let skip = app.buttons["Skip"]
        XCTAssertTrue(skip.waitForExistence(timeout: 8), "Skip button on welcome step never appeared")
        skip.tap()

        // Switch to the Podcast tab. The label is "Podcast" (the navigation
        // title inside the tab is "Podcast Setup").
        let podcastTab = app.tabBars.buttons["Podcast"]
        XCTAssertTrue(podcastTab.waitForExistence(timeout: 8), "Podcast tab not found")
        podcastTab.tap()

        XCTAssertTrue(
            app.staticTexts["Podcast Setup"].waitForExistence(timeout: 5),
            "Podcast Setup screen did not appear"
        )

        // Top of the form: You / Format / Voice cast.
        attach("setup-01-top")

        // Mid-form: scroll until the Style section's Include weather toggle is
        // visible — that's where the new GPS-backed location row lives.
        let weatherToggle = app.switches["Include weather"]
        var scrolls = 0
        while !weatherToggle.isHittable, scrolls < 6 {
            app.swipeUp()
            scrolls += 1
        }
        attach("setup-02-style-weather")

        // Bottom of form: scroll further to reveal the Duration circles + the
        // delivery schedule section. The Duration label sits inside a Form
        // section header; scroll until we can see it.
        let durationHeader = app.staticTexts["Duration"]
        scrolls = 0
        while !durationHeader.isHittable, scrolls < 6 {
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
