// This file is auto-generated from the OpenAPI spec.
// Run `make swagger && make web:types` to regenerate.
//
// Placeholder types until spec is generated:

export interface paths {
  '/health': {
    get: {
      responses: {
        200: {
          content: {
            'application/json': {
              status: string
              defra?: string
            }
          }
        }
      }
    }
  }
  '/ready': {
    get: {
      responses: {
        200: {
          content: {
            'application/json': {
              status: string
              defra?: string
            }
          }
        }
      }
    }
  }
  '/status': {
    get: {
      responses: {
        200: {
          content: {
            'application/json': {
              server: string
              providers?: {
                ocr?: string[]
                llm?: string[]
              }
              defra?: {
                container?: string
                health?: string
                url?: string
              }
            }
          }
        }
      }
    }
  }
  '/api/books': {
    get: {
      responses: {
        200: {
          content: {
            'application/json': {
              books: Array<{
                id: string
                title: string
                author?: string
                page_count: number
                status: string
                created_at?: string
              }>
            }
          }
        }
      }
    }
  }
  '/api/books/{id}': {
    get: {
      parameters: {
        path: {
          id: string
        }
      }
      responses: {
        200: {
          content: {
            'application/json': {
              id: string
              title: string
              author?: string
              page_count: number
              status: string
              created_at?: string
            }
          }
        }
      }
    }
  }
  '/api/books/{id}/cost': {
    get: {
      parameters: {
        path: {
          id: string
        }
        query?: {
          by?: string
        }
      }
      responses: {
        200: {
          content: {
            'application/json': {
              total_cost_usd: number
              breakdown?: Record<string, number>
            }
          }
        }
      }
    }
  }
  '/api/jobs': {
    get: {
      parameters?: {
        query?: {
          status?: string
          job_type?: string
        }
      }
      responses: {
        200: {
          content: {
            'application/json': {
              jobs: Array<{
                id: string
                job_type: string
                status: string
                created_at?: string
                updated_at?: string
                error?: string
                metadata?: Record<string, unknown>
              }>
            }
          }
        }
      }
    }
  }
  '/api/jobs/{id}': {
    get: {
      parameters: {
        path: {
          id: string
        }
      }
      responses: {
        200: {
          content: {
            'application/json': {
              id: string
              job_type: string
              status: string
              created_at?: string
              updated_at?: string
              error?: string
              metadata?: Record<string, unknown>
              live_status?: Record<string, string>
              progress?: Record<string, {
                completed?: number
                failed?: number
                total?: number
              }>
              worker_status?: Record<string, {
                queue_depth?: number
                active_workers?: number
              }>
              pending_units?: number
            }
          }
        }
      }
    }
    patch: {
      parameters: {
        path: {
          id: string
        }
      }
      requestBody: {
        content: {
          'application/json': {
            status?: string
            error?: string
            metadata?: Record<string, unknown>
          }
        }
      }
      responses: {
        200: {
          content: {
            'application/json': {
              id: string
              job_type: string
              status: string
              created_at?: string
              updated_at?: string
              error?: string
              metadata?: Record<string, unknown>
            }
          }
        }
      }
    }
    delete: {
      parameters: {
        path: {
          id: string
        }
      }
      responses: {
        204: {
          content: never
        }
      }
    }
  }
  '/api/jobs/start/{book_id}': {
    post: {
      parameters: {
        path: {
          book_id: string
        }
      }
      requestBody?: {
        content: {
          'application/json': {
            job_type?: string
          }
        }
      }
      responses: {
        202: {
          content: {
            'application/json': {
              job_id: string
              job_type: string
              book_id: string
              status: string
            }
          }
        }
      }
    }
  }
  '/api/jobs/status/{book_id}': {
    get: {
      parameters: {
        path: {
          book_id: string
        }
        query?: {
          job_type?: string
        }
      }
      responses: {
        200: {
          content: {
            'application/json': {
              book_id: string
              job_type: string
              total_pages: number
              ocr_complete: number
              blend_complete: number
              label_complete: number
              metadata_complete: boolean
              toc_found: boolean
              toc_extracted: boolean
              is_complete: boolean
            }
          }
        }
      }
    }
  }
  '/api/metrics': {
    get: {
      responses: {
        200: {
          content: {
            'application/json': {
              metrics: unknown[]
              count: number
            }
          }
        }
      }
    }
  }
  '/api/metrics/cost': {
    get: {
      responses: {
        200: {
          content: {
            'application/json': {
              total_cost_usd: number
              breakdown?: Record<string, number>
            }
          }
        }
      }
    }
  }
  '/api/metrics/summary': {
    get: {
      responses: {
        200: {
          content: {
            'application/json': {
              count: number
              total_cost_usd: number
              total_tokens: number
              total_time_seconds: number
              success_count: number
              error_count: number
              avg_cost_usd: number
              avg_tokens: number
              avg_time_seconds: number
            }
          }
        }
      }
    }
  }
}
