import Foundation

struct PlanRequest: Codable {
    let budgetPkr: Int
    let householdSize: Int
    let days: Int
    let restrictions: [String]
    let preferences: [String]
}

struct MealPlan: Codable, Identifiable {
    let id: String
    let request: PlanRequest
    let meals: [Meal]
    let shoppingList: ShoppingList
    let remainingBudgetPkr: Int
    var startsOn: Date?
}

struct Meal: Codable, Identifiable {
    let day: Int
    let slot: String
    let batch: Batch

    var id: String { "\(day)-\(slot)" }
}

struct Batch: Codable {
    var id: String?
    let name: String
    let category: String
    let servings: Int
    let minutes: Int
    let ingredients: [IngredientAmount]
    let instructions: [String]
    let costPaisa: Int?
}

struct CatalogRecipe: Decodable, Identifiable {
    let id: String
    let name: String
    let category: String
    let servings: Int
    let minutes: Int
    let ingredients: [IngredientAmount]
    let instructions: [String]

    var batch: Batch {
        Batch(id: id, name: name, category: category, servings: servings, minutes: minutes,
              ingredients: ingredients, instructions: instructions, costPaisa: nil)
    }
}

struct CatalogIngredient: Decodable, Identifiable {
    let id: String
    let name: String
    let category: String
    let unit: String
    let packageQuantity: Int
    let packagePricePkr: Int
}

struct IngredientAmount: Codable, Identifiable {
    let id: String
    let name: String
    let unit: String
    let quantity: Int
}

struct ShoppingList: Codable {
    let planId: String
    let totalCostPkr: Int
    let items: [ShoppingItem]
}

struct ShoppingItem: Codable, Identifiable {
    let id: String
    let name: String
    let category: String
    let unit: String
    let quantity: Int
    let packageQuantity: Int
    let packages: Int
    let purchaseQuantity: Int
    let costPkr: Int
}

private struct ServerFailure: Codable {
    let message: String
}

struct APIClient {
    let server: String

    func recipes() async throws -> [CatalogRecipe] {
        try await send(request(path: "recipes"), expecting: 200)
    }

    func ingredients() async throws -> [CatalogIngredient] {
        try await send(request(path: "ingredients"), expecting: 200)
    }

    func generate(_ configuration: PlanRequest) async throws -> MealPlan {
        var request = try request(path: "meal-plans/generate")
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        request.httpBody = try encoder.encode(configuration)
        return try await send(request, expecting: 201)
    }

    private func request(path: String) throws -> URLRequest {
        guard let base = URL(string: server.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = base.scheme, ["http", "https"].contains(scheme), base.host != nil else {
            throw Failure.invalidAddress
        }
        return URLRequest(url: base.appending(path: path), timeoutInterval: 20)
    }

    private func send<Response: Decodable>(_ request: URLRequest, expecting status: Int) async throws -> Response {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            try Task.checkCancellation()
            throw Failure.message("Couldn’t reach the meal planner. Start the backend and check its address.")
        }
        guard let http = response as? HTTPURLResponse, http.statusCode == status else {
            let failure = try? JSONDecoder().decode(ServerFailure.self, from: data)
            throw Failure.message(failure?.message ?? (status == 201
                ? "The backend couldn’t generate a plan. Check your settings and try again."
                : "The backend couldn’t load the catalog. Try again."))
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Response.self, from: data)
    }

    enum Failure: LocalizedError {
        case invalidAddress
        case message(String)

        var errorDescription: String? {
            switch self {
            case .invalidAddress: "Enter a complete backend address, such as http://127.0.0.1:8000."
            case .message(let message): message
            }
        }
    }
}
