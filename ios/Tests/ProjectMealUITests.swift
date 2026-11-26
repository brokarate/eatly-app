import XCTest

final class ProjectMealUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testMealPlanRecipeAndShoppingChecklist() {
        let app = XCUIApplication()
        app.launch()
        let generate = app.buttons["Generate meal plan"]
        XCTAssertTrue(generate.waitForExistence(timeout: 5))
        XCTAssertTrue(generate.isHittable)
        let dockY = generate.frame.midY
        reveal(app.descendants(matching: .any)["planner-developer-settings"].firstMatch, in: app)
        scroll(app, upward: true)
        XCTAssertTrue(generate.isHittable)
        XCTAssertEqual(generate.frame.midY, dockY, accuracy: 2)
        generate.tap()

        XCTAssertTrue(app.navigationBars["Your meal plan"].waitForExistence(timeout: 25))
        XCTAssertTrue(app.staticTexts["Meal calendar"].exists)
        XCTAssertTrue(app.staticTexts["Estimated checkout"].exists)
        XCTAssertTrue(app.staticTexts["Budget left"].exists)
        XCTAssertFalse(app.buttons["calendar-day-4"].isEnabled)
        app.buttons["calendar-day-3"].tap()
        let lunch = app.buttons["meal-3-lunch"]
        XCTAssertTrue(lunch.isHittable)
        lunch.tap()
        XCTAssertTrue(app.navigationBars["Recipe"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Ingredients for this batch"].exists)
        app.navigationBars["Recipe"].buttons.firstMatch.tap()

        reveal(app.buttons["Shopping list"], in: app, upward: false)
        app.buttons["Shopping list"].tap()
        XCTAssertTrue(app.navigationBars["Shopping list"].waitForExistence(timeout: 5))
        let row = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "shopping-item-")).firstMatch
        reveal(row, in: app)
        let original = row.value as? String
        XCTAssertEqual(original, "Not purchased")
        let identifier = row.identifier
        row.tap()
        XCTAssertEqual(row.value as? String, "Purchased")

        app.terminate()
        app.launch()
        app.buttons["meal-tab-Week"].tap()
        XCTAssertTrue(app.navigationBars["Your meal plan"].waitForExistence(timeout: 5))
        reveal(app.buttons["Shopping list"], in: app)
        app.buttons["Shopping list"].tap()
        let savedRow = app.buttons[identifier]
        reveal(savedRow, in: app)
        XCTAssertEqual(savedRow.value as? String, "Purchased")

        app.buttons["meal-tab-Profile"].tap()
        XCTAssertTrue(app.navigationBars["Profile"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Friends’ table"].exists)
        app.buttons["Edit profile"].tap()
        XCTAssertTrue(app.navigationBars["Edit profile"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["Display name"].exists)
        XCTAssertTrue(app.textFields["Username"].exists)
        XCTAssertTrue(app.textFields["City"].exists)
        app.buttons["meal-tab-Plan"].tap()
        XCTAssertTrue(app.navigationBars["Project Meal"].waitForExistence(timeout: 5))
    }

    func testBrowseSearchesRecipesAndIngredients() {
        let app = XCUIApplication()
        app.launch()
        app.buttons["meal-tab-Browse"].tap()
        XCTAssertTrue(app.navigationBars["Browse"].waitForExistence(timeout: 5))
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("karahi")
        let recipe = app.buttons["catalog-recipe-karahi"]
        XCTAssertTrue(recipe.waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["catalog-recipe-chana"].exists)
        recipe.tap()
        XCTAssertTrue(app.navigationBars["Recipe"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Chicken karahi with roti"].exists)
        let heart = app.buttons["favorite-toggle"]
        XCTAssertTrue(heart.exists)
        let alreadySaved = heart.label == "Remove from favorites"
        if !alreadySaved { heart.tap() }
        XCTAssertEqual(heart.label, "Remove from favorites")

        app.terminate()
        app.launch()
        app.buttons["meal-tab-Browse"].tap()
        app.segmentedControls.buttons["Ingredients"].tap()
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        search.typeText("tomato")
        let ingredient = app.buttons["catalog-ingredient-tomato"]
        XCTAssertTrue(ingredient.waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["catalog-ingredient-atta"].exists)
        ingredient.tap()
        XCTAssertTrue(app.navigationBars["Ingredient"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Tomatoes"].exists)
        let ingredientSaved = heart.label == "Remove from favorites"
        if !ingredientSaved { heart.tap() }
        XCTAssertEqual(heart.label, "Remove from favorites")

        app.buttons["meal-tab-Profile"].tap()
        app.buttons["View favorites"].tap()
        XCTAssertTrue(app.navigationBars["Favorites"].waitForExistence(timeout: 5))
        XCTAssertTrue(recipe.waitForExistence(timeout: 10))
        if !alreadySaved {
            recipe.tap()
            heart.tap()
            app.navigationBars["Recipe"].buttons.firstMatch.tap()
            XCTAssertFalse(recipe.exists)
        }

        app.segmentedControls.buttons["Ingredients"].tap()
        XCTAssertTrue(ingredient.waitForExistence(timeout: 10))
        if !ingredientSaved {
            ingredient.tap()
            heart.tap()
            app.navigationBars["Ingredient"].buttons.firstMatch.tap()
            XCTAssertFalse(ingredient.exists)
        }
    }

    func testSwipesSwitchAdjacentTabs() {
        let app = XCUIApplication()
        app.launch()
        let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.78, dy: 0.45))
        let end = app.coordinate(withNormalizedOffset: CGVector(dx: 0.22, dy: 0.45))
        for title in ["Week", "Browse", "Profile"] {
            start.press(forDuration: 0.05, thenDragTo: end)
            let tab = app.buttons["meal-tab-\(title)"]
            let selected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "selected == true"), object: tab)
            XCTAssertEqual(XCTWaiter.wait(for: [selected], timeout: 3), .completed, "Expected \(title)")
            if title == "Browse" {
                XCTAssertTrue(app.navigationBars["Browse"].waitForExistence(timeout: 5))
            }
        }
        for title in ["Browse", "Week", "Plan"] {
            end.press(forDuration: 0.05, thenDragTo: start)
            let tab = app.buttons["meal-tab-\(title)"]
            let selected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "selected == true"), object: tab)
            XCTAssertEqual(XCTWaiter.wait(for: [selected], timeout: 3), .completed, "Expected \(title)")
            if title == "Browse" {
                XCTAssertTrue(app.navigationBars["Browse"].waitForExistence(timeout: 5))
            }
        }
    }

    func testPartialSwipeSnapsBack() {
        let app = XCUIApplication()
        app.launch()
        let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.75, dy: 0.45))
        let partial = app.coordinate(withNormalizedOffset: CGVector(dx: 0.44, dy: 0.45))
        start.press(forDuration: 0.05, thenDragTo: partial, withVelocity: .slow, thenHoldForDuration: 5)
        XCTAssertTrue(app.buttons["meal-tab-Plan"].isSelected)
        XCTAssertTrue(app.navigationBars["Project Meal"].exists)
    }

    func testLowBudgetShowsBackendError() {
        let app = XCUIApplication()
        app.launch()
        let budget = app.textFields["grocery-budget"]
        XCTAssertTrue(budget.waitForExistence(timeout: 5))
        app.buttons["clear-budget"].tap()
        budget.tap()
        budget.typeText("1")
        XCTAssertEqual(budget.value as? String, "1")
        XCTAssertTrue(app.buttons["Generate meal plan"].isHittable)
        app.buttons["Generate meal plan"].tap()
        let error = app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "sample prices")).firstMatch
        XCTAssertTrue(error.waitForExistence(timeout: 25))
    }

    func testStandardDarkAcrossAllTabs() {
        let app = XCUIApplication()
        app.launch()
        app.buttons["meal-tab-Profile"].tap()
        let appearance = app.buttons["meal-appearance"]
        reveal(appearance, in: app)
        appearance.tap()
        app.buttons["Light"].tap()
        XCTAssertEqual(appearance.value as? String, "Light")
        capture("Live Light Profile", in: app)
        appearance.tap()
        app.buttons["Dark"].tap()
        XCTAssertEqual(appearance.value as? String, "Dark")
        capture("Live Dark Profile", in: app)
        app.buttons["meal-tab-Plan"].tap()
        XCTAssertTrue(app.navigationBars["Project Meal"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["grocery-budget"].exists)
        capture("Dark Planner", in: app)

        let household = app.buttons["household-6"]
        reveal(household, in: app)
        household.tap()
        XCTAssertTrue(app.staticTexts["6 people selected"].exists)
        XCTAssertTrue(household.isSelected)

        let duration = app.buttons["duration-5"]
        reveal(duration, in: app)
        duration.tap()
        XCTAssertTrue(duration.isSelected)
        XCTAssertFalse(app.buttons["duration-3"].isSelected)

        let vegetarian = app.buttons["choice-vegetarian"]
        reveal(vegetarian, in: app)
        vegetarian.tap()
        XCTAssertTrue(vegetarian.isSelected)
        capture("Dark Planner Choices", in: app)
        XCTAssertTrue(app.buttons["Generate meal plan"].isHittable)
        app.buttons["Generate meal plan"].tap()
        XCTAssertTrue(app.navigationBars["Your meal plan"].waitForExistence(timeout: 25))
        XCTAssertTrue(app.staticTexts["Meal calendar"].exists)
        capture("Dark Week", in: app)
        app.terminate()
        app.launch()
        app.buttons["meal-tab-Profile"].tap()
        reveal(appearance, in: app)
        XCTAssertEqual(appearance.value as? String, "Dark")
        capture("Relaunched Dark Profile", in: app)
        appearance.tap()
        app.buttons["Light"].tap()
        capture("Restored Light Profile", in: app)
        appearance.tap()
        app.buttons["System"].tap()
    }

    private func capture(_ name: String, in app: XCUIApplication) {
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    private func reveal(_ element: XCUIElement, in app: XCUIApplication, upward: Bool = true) {
        let generate = app.buttons["Generate meal plan"]
        for _ in 0..<8 {
            if element.isHittable &&
                (!generate.exists || element.frame.maxY <= generate.frame.minY) {
                return
            }
            scroll(app, upward: upward)
        }
        XCTFail("Could not scroll \(element) fully into view")
    }

    private func scroll(_ app: XCUIApplication, upward: Bool) {
        let upper = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.27))
        let lower = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.68))
        (upward ? lower : upper).press(forDuration: 0.05, thenDragTo: upward ? upper : lower)
    }

}
