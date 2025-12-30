// Package docs provides generated OpenAPI documentation.
//
// Shelf API
//
//	@title			Shelf API
//	@version		1.0
//	@description	Book digitization pipeline API for managing books, jobs, and processing.
//	@termsOfService	http://swagger.io/terms/
//
//	@contact.name	API Support
//	@contact.url	https://github.com/jackzampolin/shelf
//
//	@license.name	MIT
//	@license.url	https://opensource.org/licenses/MIT
//
//	@host		localhost:8080
//	@BasePath	/
//
//	@schemes	http https
package docs

//go:generate swag init -g ../cmd/shelf/serve.go -o ./swagger --parseDependency --parseInternal
