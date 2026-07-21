import { NextResponse } from "next/server";
import { clientPromise, dbName } from "@/lib/mongodb";
import { PAGINATION_PER_PAGE } from "@/lib/constants";

// Semantic product search. When the shopper types a query we embed it with
// VoyageAI (voyage-3-large, the same model the catalog was embedded with) and
// run Atlas Vector Search over the product embeddings, so results match by
// meaning rather than keywords. With no query we fall back to a plain browse of
// the catalog (with the same facet filtering as before).
const VOYAGE_MODEL = "voyage-3-large";
const VECTOR_INDEX = process.env.VECTOR_INDEX_NAME || "vs_index_vai_text_embeddings";
const EMBEDDING_FIELD = "vai_text_embedding";

async function embedQuery(text) {
  const apiKey = process.env.VOYAGE_API_KEY;
  if (!apiKey) throw new Error("VOYAGE_API_KEY is not set");
  const res = await fetch("https://api.voyageai.com/v1/embeddings", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ input: [text], model: VOYAGE_MODEL, input_type: "query" }),
  });
  if (!res.ok) {
    throw new Error(`VoyageAI embedding failed: ${res.status} ${await res.text()}`);
  }
  const data = await res.json();
  return data.data[0].embedding;
}

function facetStages(facets) {
  const stages = [];
  if (facets) {
    const { selectedBrands, selectedCategories } = facets;
    if (selectedBrands && selectedBrands.length > 0) {
      stages.push({ $match: { brand: { $in: selectedBrands } } });
    }
    if (selectedCategories && selectedCategories.length > 0) {
      stages.push({ $match: { masterCategory: { $in: selectedCategories } } });
    }
  }
  return stages;
}

export async function POST(request) {
  const { query, facets, pagination_page } = await request.json();

  try {
    const client = await clientPromise;
    const db = client.db(dbName);
    const collection = db.collection("products");

    let pipeline = [];

    if (query) {
      // Semantic path: embed the query, then Atlas Vector Search. $vectorSearch
      // must be the first stage; facets are applied as a post-filter.
      const queryVector = await embedQuery(query);
      pipeline.push({
        $vectorSearch: {
          index: VECTOR_INDEX,
          path: EMBEDDING_FIELD,
          queryVector,
          numCandidates: 150,
          limit: 60,
        },
      });
      pipeline.push(...facetStages(facets));
      pipeline.push({ $addFields: { score: { $meta: "vectorSearchScore" } } });
      pipeline.push({ $project: { vai_text_embedding: 0 } });
    } else {
      // Browse path: no query, just facet filtering over the catalog.
      pipeline.push(...facetStages(facets));
      pipeline.push({ $project: { vai_text_embedding: 0 } });
      pipeline.push({ $limit: 3000 });
    }

    const totalCount = await collection
      .aggregate(pipeline.concat([{ $count: "total" }]))
      .toArray();
    const totalItems = totalCount.length > 0 ? totalCount[0].total : 0;

    const products = await collection
      .aggregate(pipeline)
      .skip(PAGINATION_PER_PAGE * pagination_page)
      .limit(PAGINATION_PER_PAGE)
      .toArray();

    console.log("RESULTS LENGTH: ", products.length);
    return NextResponse.json(
      { products: products, totalItems: totalItems },
      { status: 200 }
    );
  } catch (error) {
    console.error(error);
    return new Response(JSON.stringify({ error: "Internal Server Error" }), {
      status: 500,
    });
  }
}
